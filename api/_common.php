<?php
// Shared helpers for the API: own SQLite database + own PHP sessions (isolated from any other app on the NAS).
// The Python engine lives in ../engine and the database in ../data (both blocked by .htaccess).

if (realpath($_SERVER['SCRIPT_FILENAME'] ?? '') === __FILE__) {
    http_response_code(404);
    exit;
}

const IMAGE_TYPES = [
    IMAGETYPE_JPEG => 'jpg',
    IMAGETYPE_PNG => 'png',
    IMAGETYPE_WEBP => 'webp',
    IMAGETYPE_GIF => 'gif',
    IMAGETYPE_BMP => 'bmp',
    IMAGETYPE_TIFF_II => 'tif',
    IMAGETYPE_TIFF_MM => 'tif',
];
const JOB_RETENTION_SECONDS = 7 * 24 * 3600;
const SESSION_LIFETIME = 60 * 24 * 3600;
const TRASH_RETENTION_SECONDS = 30 * 24 * 3600; // data/trash/ files older than this are deleted automatically
const ADMIN_USERNAME = 'ggonmar'; // owner: always a superuser and cannot be demoted by anyone
const USERS_PER_PAGE = 20;
const MARK_TABLES = ['seen' => 'seen', 'favorite' => 'favorites'];

$ROOT = dirname(__DIR__);
$ENGINE_DIR = $ROOT . '/engine';
$PAINTINGS_DIR = $ROOT . '/paintings';
$JOBS_DIR = $ENGINE_DIR . '/jobs';
$DATA_DIR = $ROOT . '/data';

function json_response(int $status, array $data): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

function db(): PDO
{
    static $pdo = null;
    global $DATA_DIR;
    if ($pdo) {
        return $pdo;
    }
    $dbFile = $DATA_DIR . '/cuadros.sqlite';
    umask(0007); // keep the DB (and its journal) writable for ggonmar via the share ACLs (engine over SSH)
    $pdo = new PDO('sqlite:' . $dbFile, null, null, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    ]);
    if (is_file($dbFile) && fileowner($dbFile) === getmyuid() && (fileperms($dbFile) & 0660) !== 0660) {
        @chmod($dbFile, 0660);
    }
    $pdo->exec('PRAGMA foreign_keys = ON');
    $pdo->exec('PRAGMA busy_timeout = 5000');
    // Same schema file as the Python engine
    $pdo->exec(file_get_contents($GLOBALS['ENGINE_DIR'] . '/schema.sql'));
    // Columns added after the users table was first created
    $columns = array_column($pdo->query('PRAGMA table_info(users)')->fetchAll(), 'name');
    if (!in_array('can_upload', $columns, true)) {
        $pdo->exec('ALTER TABLE users ADD COLUMN can_upload INTEGER NOT NULL DEFAULT 0');
    }
    if (!in_array('last_login_at', $columns, true)) {
        $pdo->exec('ALTER TABLE users ADD COLUMN last_login_at TEXT');
    }
    if (!in_array('theme', $columns, true)) {
        $pdo->exec('ALTER TABLE users ADD COLUMN theme TEXT');
    }
    $collectionColumns = array_column($pdo->query('PRAGMA table_info(collections)')->fetchAll(), 'name');
    if (!in_array('kind', $collectionColumns, true)) {
        $pdo->exec("ALTER TABLE collections ADD COLUMN kind TEXT NOT NULL DEFAULT 'custom'");
    }
    $pdo->exec("CREATE UNIQUE INDEX IF NOT EXISTS idx_collections_one_favorites ON collections(user_id) WHERE kind = 'favorites'");
    $paintingColumns = array_column($pdo->query('PRAGMA table_info(paintings)')->fetchAll(), 'name');
    if (!in_array('status', $paintingColumns, true)) {
        $pdo->exec("ALTER TABLE paintings ADD COLUMN status TEXT NOT NULL DEFAULT 'ready'");
    }
    return $pdo;
}

function start_session(): void
{
    global $DATA_DIR;
    if (session_status() === PHP_SESSION_ACTIVE) {
        return;
    }
    $sessionDir = $DATA_DIR . '/sessions';
    if (!is_dir($sessionDir)) {
        mkdir($sessionDir, 0770, true);
    }
    ini_set('session.gc_maxlifetime', (string) SESSION_LIFETIME);
    ini_set('session.gc_probability', '1');
    ini_set('session.gc_divisor', '100');
    ini_set('session.use_strict_mode', '1');
    session_save_path($sessionDir);
    session_name('CUADROS_SID');
    session_set_cookie_params([
        'lifetime' => SESSION_LIFETIME,
        'path' => rtrim(dirname(dirname($_SERVER['SCRIPT_NAME'])), '/') . '/',
        'httponly' => true,
        'samesite' => 'Lax',
        'secure' => !empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off',
    ]);
    session_start();
}

function current_user(): ?array
{
    // Anonymous visitors never get a session file: one is only created when logging in/registering
    if (empty($_COOKIE['CUADROS_SID'])) {
        return null;
    }
    start_session();
    $id = $_SESSION['user_id'] ?? null;
    if (!$id) {
        end_session();
        return null;
    }
    $stmt = db()->prepare('SELECT id, username, password_hash, can_upload, theme FROM users WHERE id = ?');
    $stmt->execute([$id]);
    $user = $stmt->fetch();
    // A password change invalidates every other session of that user
    if (!$user || !hash_equals(session_password_tag($user), (string) ($_SESSION['pw_tag'] ?? ''))) {
        end_session();
        return null;
    }
    return $user;
}

// Deletes the session file and the cookie (logout, expired or invalidated sessions)
function end_session(): void
{
    if (session_status() === PHP_SESSION_ACTIVE) {
        $_SESSION = [];
        session_destroy();
    }
    $params = session_get_cookie_params();
    setcookie('CUADROS_SID', '', [
        'expires' => time() - 3600,
        'path' => $params['path'],
        'httponly' => true,
        'samesite' => 'Lax',
        'secure' => $params['secure'],
    ]);
    unset($_COOKIE['CUADROS_SID']);
}

// ---- Trash (data/trash/): deleted paintings and replaced images, kept TRASH_RETENTION_SECONDS ----

function trash_dir(): string
{
    global $DATA_DIR;
    $dir = $DATA_DIR . '/trash';
    if (!is_dir($dir)) {
        mkdir($dir, 0770, true);
    }
    return $dir;
}

// Moves a file into the trash as $name; returns its new path, or null on failure
function move_to_trash(string $path, string $name): ?string
{
    $target = trash_dir() . '/' . $name;
    if (!rename($path, $target)) {
        return null;
    }
    touch($target); // rename() keeps the original date; retention counts from the moment it was trashed
    purge_trash(true);
    return $target;
}

// Deletes trash files older than the retention. Unless forced, runs at most once a day (cheap to call anywhere)
function purge_trash(bool $force = false): void
{
    $dir = trash_dir();
    $marker = $dir . '/.last_purge';
    if (!$force && is_file($marker) && filemtime($marker) > time() - 24 * 3600) {
        return;
    }
    @touch($marker);
    foreach (glob($dir . '/*') ?: [] as $file) {
        if (is_file($file) && filemtime($file) < time() - TRASH_RETENTION_SECONDS) {
            @unlink($file);
        }
    }
}

function session_password_tag(array $user): string
{
    return hash('sha256', $user['password_hash']);
}

// The superadmin is decided by username (not by a DB flag), so nobody can grant it to themselves
// The owner is decided by username (not by a DB flag), so nobody can take that role away
function is_owner(array $user): bool
{
    return strcasecmp($user['username'], ADMIN_USERNAME) === 0;
}

// Superusers = the owner + every user with the "can upload" permission. They have the same powers:
// upload, edit/delete paintings, users dashboard (grant/revoke the permission) and AI settings.
function is_superadmin(array $user): bool
{
    return is_owner($user) || !empty($user['can_upload']);
}

function can_upload(array $user): bool
{
    return is_superadmin($user);
}

function public_user(array $user): array
{
    return [
        'username' => $user['username'],
        'is_admin' => is_superadmin($user),
        'can_upload' => can_upload($user),
        'theme' => in_array($user['theme'] ?? null, ['light', 'dark'], true) ? $user['theme'] : null,
    ];
}

function require_user(): array
{
    $user = current_user();
    if (!$user) {
        json_response(401, ['error' => 'Tienes que iniciar sesión']);
    }
    return $user;
}

function require_admin(): array
{
    $user = require_user();
    if (!is_superadmin($user)) {
        json_response(403, ['error' => 'Necesitas ser superusuario para hacer esto']);
    }
    return $user;
}

function require_uploader(): array
{
    $user = require_user();
    if (!can_upload($user)) {
        json_response(403, ['error' => 'No tienes permiso para subir cuadros']);
    }
    return $user;
}

// State-changing requests must be POST and carry a custom header (blocks cross-site form posts / CSRF).
function require_post(): void
{
    if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
        json_response(405, ['error' => 'Método no permitido']);
    }
    if (($_SERVER['HTTP_X_CUADROS'] ?? '') !== '1') {
        json_response(400, ['error' => 'Petición inválida']);
    }
}

function json_input(): array
{
    $data = json_decode(file_get_contents('php://input') ?: '', true);
    return is_array($data) ? $data : [];
}

function valid_job_id(string $id): bool
{
    return (bool) preg_match('/^[a-f0-9]{16}$/', $id);
}

function valid_painting_id($id): bool
{
    return is_string($id) && (bool) preg_match('/^[a-f0-9]{12}$/', $id);
}

// escapeshellarg() silently strips non-ASCII characters when PHP's LC_CTYPE is not UTF-8 (the NAS default),
// so "café.jpg" became "caf.jpg" and the engine could not find uploaded files. Plain POSIX single-quoting is safe.
function shell_quote(string $value): string
{
    return "'" . str_replace("'", "'\\''", $value) . "'";
}

function engine_config(): array
{
    global $ENGINE_DIR;
    $config = json_decode(@file_get_contents($ENGINE_DIR . '/config.json') ?: '', true);
    if (!is_array($config)) {
        json_response(500, ['error' => 'No se pudo leer engine/config.json']);
    }
    // AI provider/model chosen from the web (same override the Python ConfigManager applies)
    $ai = json_decode(@file_get_contents($ENGINE_DIR . '/ai_settings.json') ?: '', true);
    foreach (['data_source', 'ollama_model', 'gemini_model', 'description_style', 'description_max_length'] as $key) {
        if (!empty($ai[$key])) {
            $config[$key] = $ai[$key];
        }
    }
    return $config;
}

function engine_command(array $args): string
{
    global $ENGINE_DIR, $JOBS_DIR;
    $tmp = "$JOBS_DIR/tmp";
    @mkdir($tmp, 0775, true);
    return 'cd ' . shell_quote($ENGINE_DIR)
        . ' && TMPDIR=' . shell_quote($tmp) . ' PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1 '
        . shell_quote("$ENGINE_DIR/.venv/bin/python") . ' '
        . implode(' ', array_map('shell_quote', $args));
}

// Run an engine script in the background; api/job.php reports its progress (log.txt, result.json, exit_code).
function start_engine_job(array $args, array $meta): string
{
    global $JOBS_DIR;
    foreach (glob("$JOBS_DIR/*", GLOB_ONLYDIR) ?: [] as $old) {
        if (valid_job_id(basename($old)) && filemtime($old) < time() - JOB_RETENTION_SECONDS) {
            array_map('unlink', glob("$old/*") ?: []);
            @rmdir($old);
        }
    }

    $jobId = bin2hex(random_bytes(8));
    $jobDir = "$JOBS_DIR/$jobId";
    if (!mkdir($jobDir, 0775, true)) {
        json_response(500, ['error' => 'No se pudo crear el trabajo']);
    }
    file_put_contents("$jobDir/meta.json", json_encode($meta + ['created_at' => date(DATE_ATOM)], JSON_UNESCAPED_UNICODE));

    $cmd = engine_command(array_merge($args, ['--result-json', "$jobDir/result.json"]))
        . ' > ' . shell_quote("$jobDir/log.txt") . ' 2>&1'
        . '; echo $? > ' . shell_quote("$jobDir/exit_code");
    exec('setsid sh -c ' . shell_quote($cmd) . ' > /dev/null 2>&1 &');
    return $jobId;
}
