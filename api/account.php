<?php
// GET: current user + their seen/favorite paintings.
// POST {action: register|login|logout|change_password, ...}
require __DIR__ . '/_common.php';

function account_state(?array $user): array
{
    if (!$user) {
        return ['user' => null, 'seen' => [], 'favorites' => []];
    }
    $marks = [];
    foreach (MARK_TABLES as $type => $table) {
        $stmt = db()->prepare("SELECT painting_id FROM $table WHERE user_id = ? ORDER BY created_at");
        $stmt->execute([$user['id']]);
        $marks[$type] = $stmt->fetchAll(PDO::FETCH_COLUMN);
    }
    return ['user' => public_user($user), 'seen' => $marks['seen'], 'favorites' => $marks['favorite']];
}

function log_in(array $user): void
{
    session_regenerate_id(true);
    $_SESSION['user_id'] = (int) $user['id'];
    $_SESSION['pw_tag'] = session_password_tag($user);
    db()->prepare('UPDATE users SET last_login_at = ? WHERE id = ?')->execute([gmdate('Y-m-d\TH:i:s') . '+00:00', $user['id']]);
}

function check_password_strength(string $password): void
{
    if (mb_strlen($password) < 6) {
        json_response(400, ['error' => 'La contraseña debe tener al menos 6 caracteres']);
    }
}

if ($_SERVER['REQUEST_METHOD'] === 'GET') {
    json_response(200, account_state(current_user()));
}

require_post();
start_session();
$input = json_input();
$action = $input['action'] ?? '';
$username = trim((string) ($input['username'] ?? ''));
$password = (string) ($input['password'] ?? '');

switch ($action) {
    case 'register':
        if (!preg_match('/^[A-Za-z0-9._-]{3,32}$/', $username)) {
            json_response(400, ['error' => 'El usuario debe tener 3-32 caracteres (letras, números, punto, guion o guion bajo)']);
        }
        check_password_strength($password);
        try {
            $stmt = db()->prepare('INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)');
            $stmt->execute([$username, password_hash($password, PASSWORD_DEFAULT), strcasecmp($username, ADMIN_USERNAME) === 0 ? 1 : 0]);
        } catch (PDOException $e) {
            json_response(409, ['error' => 'Ese nombre de usuario ya existe']);
        }
        $stmt = db()->prepare('SELECT * FROM users WHERE id = ?');
        $stmt->execute([db()->lastInsertId()]);
        $user = $stmt->fetch();
        log_in($user);
        json_response(200, account_state($user));

    case 'login':
        $stmt = db()->prepare('SELECT * FROM users WHERE username = ?');
        $stmt->execute([$username]);
        $user = $stmt->fetch();
        if (!$user || !password_verify($password, $user['password_hash'])) {
            usleep(800000); // slow down password guessing
            json_response(401, ['error' => 'Usuario o contraseña incorrectos']);
        }
        if (password_needs_rehash($user['password_hash'], PASSWORD_DEFAULT)) {
            $user['password_hash'] = password_hash($password, PASSWORD_DEFAULT);
            db()->prepare('UPDATE users SET password_hash = ? WHERE id = ?')->execute([$user['password_hash'], $user['id']]);
        }
        log_in($user);
        json_response(200, account_state($user));

    case 'set_theme':
        $user = require_user();
        $theme = $input['theme'] ?? '';
        if (!in_array($theme, ['light', 'dark'], true)) {
            json_response(400, ['error' => 'Tema no válido']);
        }
        db()->prepare('UPDATE users SET theme = ? WHERE id = ?')->execute([$theme, $user['id']]);
        json_response(200, ['ok' => true]);

    case 'logout':
        end_session();
        json_response(200, account_state(null));

    case 'change_password':
        $user = require_user();
        if (!password_verify((string) ($input['current_password'] ?? ''), $user['password_hash'])) {
            usleep(800000);
            json_response(401, ['error' => 'La contraseña actual no es correcta']);
        }
        check_password_strength($password);
        $user['password_hash'] = password_hash($password, PASSWORD_DEFAULT);
        db()->prepare('UPDATE users SET password_hash = ? WHERE id = ?')->execute([$user['password_hash'], $user['id']]);
        log_in($user); // keeps this session; every other session of the user is now invalid
        json_response(200, ['ok' => true]);

    default:
        json_response(400, ['error' => 'Acción desconocida']);
}
