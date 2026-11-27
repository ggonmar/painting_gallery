<?php
// Users dashboard (superadmin only).
// GET  ?page=N&q=text                  -> counts + one page (USERS_PER_PAGE) of users
// POST {action: set_upload, user_id, value} -> grant/revoke permission to upload paintings
require __DIR__ . '/_common.php';

$admin = require_admin();

if ($_SERVER['REQUEST_METHOD'] === 'GET') {
    $query = trim((string) ($_GET['q'] ?? ''));
    $where = '';
    $params = [];
    if ($query !== '') {
        $where = "WHERE u.username LIKE ? ESCAPE '\\'";
        $params[] = '%' . addcslashes($query, '%_\\') . '%';
    }

    $countStmt = db()->prepare("SELECT COUNT(*) FROM users u $where");
    $countStmt->execute($params);
    $matching = (int) $countStmt->fetchColumn();
    $pages = max(1, (int) ceil($matching / USERS_PER_PAGE));
    $page = min($pages, max(1, (int) ($_GET['page'] ?? 1)));

    $stmt = db()->prepare("
        SELECT u.id, u.username, u.can_upload, u.created_at, u.last_login_at,
               (SELECT COUNT(*) FROM seen s WHERE s.user_id = u.id) AS seen_count,
               (SELECT COUNT(*) FROM favorites f WHERE f.user_id = u.id) AS favorites_count
        FROM users u $where
        ORDER BY u.created_at DESC, u.id DESC
        LIMIT " . USERS_PER_PAGE . ' OFFSET ' . (($page - 1) * USERS_PER_PAGE));
    $stmt->execute($params);

    $users = array_map(function (array $u): array {
        return [
            'id' => (int) $u['id'],
            'username' => $u['username'],
            'is_owner' => is_owner($u),
            'is_superadmin' => is_superadmin($u),
            'can_upload' => can_upload($u),
            // created_at comes from SQLite CURRENT_TIMESTAMP (UTC, no offset)
            'created_at' => $u['created_at'] ? str_replace(' ', 'T', $u['created_at']) . '+00:00' : null,
            'last_login_at' => $u['last_login_at'],
            'seen_count' => (int) $u['seen_count'],
            'favorites_count' => (int) $u['favorites_count'],
        ];
    }, $stmt->fetchAll());

    $stats = db()->query("
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN can_upload = 1 OR username = '" . ADMIN_USERNAME . "' COLLATE NOCASE THEN 1 ELSE 0 END) AS uploaders,
               SUM(CASE WHEN created_at >= datetime('now', '-30 days') THEN 1 ELSE 0 END) AS new_30_days
        FROM users
    ")->fetch();

    json_response(200, [
        'stats' => [
            'total' => (int) $stats['total'],
            'uploaders' => (int) $stats['uploaders'],
            'new_30_days' => (int) $stats['new_30_days'],
        ],
        'query' => $query,
        'matching' => $matching,
        'page' => $page,
        'pages' => $pages,
        'per_page' => USERS_PER_PAGE,
        'users' => $users,
    ]);
}

require_post();
$input = json_input();

switch ($input['action'] ?? '') {
    case 'set_upload':
        $stmt = db()->prepare('SELECT id, username FROM users WHERE id = ?');
        $stmt->execute([(int) ($input['user_id'] ?? 0)]);
        $target = $stmt->fetch();
        if (!$target) {
            json_response(404, ['error' => 'Usuario no encontrado']);
        }
        if (is_owner($target)) {
            json_response(400, ['error' => ADMIN_USERNAME . ' es el propietario y siempre es superusuario']);
        }
        if ((int) $target['id'] === (int) $admin['id'] && empty($input['value'])) {
            json_response(400, ['error' => 'No puedes quitarte a ti mismo los permisos de superusuario']);
        }
        db()->prepare('UPDATE users SET can_upload = ? WHERE id = ?')
            ->execute([!empty($input['value']) ? 1 : 0, $target['id']]);
        json_response(200, ['ok' => true]);

    default:
        json_response(400, ['error' => 'Acción desconocida']);
}
