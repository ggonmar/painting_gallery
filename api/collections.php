<?php
// Personal collections. Private to their owner; anyone with the link (?coleccion=<id>) can view one read-only.
// GET                    -> my collections (logged in)
// GET ?id=<id>           -> one collection (read-only for non-owners)
// POST {action: create, name} | {action: rename, id, name} | {action: delete, id}
// POST {action: toggle, id, painting_id, value}
// Every user also has a built-in "Favoritos" collection (kind = 'favorites'): its paintings are the user's ❤️ marks
// (table favorites), it can't be renamed or deleted, and shared it shows as "Favoritos de <username>".
require __DIR__ . '/_common.php';

const MAX_COLLECTIONS_PER_USER = 100;

function valid_collection_id($id): bool
{
    return is_string($id) && (bool) preg_match('/^[a-f0-9]{16}$/', $id);
}

function find_collection($id): array
{
    if (!valid_collection_id($id)) {
        json_response(404, ['error' => 'Colección no encontrada']);
    }
    $stmt = db()->prepare('SELECT c.*, u.username AS owner FROM collections c JOIN users u ON u.id = c.user_id WHERE c.id = ?');
    $stmt->execute([$id]);
    $collection = $stmt->fetch();
    if (!$collection) {
        json_response(404, ['error' => 'Colección no encontrada']);
    }
    return $collection;
}

function own_collection($id, array $user): array
{
    $collection = find_collection($id);
    if ((int) $collection['user_id'] !== (int) $user['id']) {
        json_response(404, ['error' => 'Colección no encontrada']);
    }
    return $collection;
}

function is_favorites(array $collection): bool
{
    return ($collection['kind'] ?? 'custom') === 'favorites';
}

// Creates the user's built-in favorites collection the first time it's needed
function ensure_favorites_collection(array $user): void
{
    db()->prepare("INSERT OR IGNORE INTO collections (id, user_id, name, kind) VALUES (?, ?, 'Favoritos', 'favorites')")
        ->execute([bin2hex(random_bytes(8)), $user['id']]);
}

function collection_payload(array $collection, ?array $user): array
{
    $mine = $user !== null && (int) $user['id'] === (int) $collection['user_id'];
    if (is_favorites($collection)) {
        $stmt = db()->prepare('SELECT painting_id FROM favorites WHERE user_id = ? ORDER BY created_at, painting_id');
        $stmt->execute([$collection['user_id']]);
        $name = $mine ? 'Favoritos' : 'Favoritos de ' . $collection['owner'];
    } else {
        $stmt = db()->prepare('SELECT painting_id FROM collection_paintings WHERE collection_id = ? ORDER BY added_at, painting_id');
        $stmt->execute([$collection['id']]);
        $name = $collection['name'];
    }
    return [
        'id' => $collection['id'],
        'name' => $name,
        'kind' => is_favorites($collection) ? 'favorites' : 'custom',
        'owner' => $collection['owner'],
        'mine' => $mine,
        'painting_ids' => $stmt->fetchAll(PDO::FETCH_COLUMN),
    ];
}

function own_custom_collection($id, array $user): array
{
    $collection = own_collection($id, $user);
    if (is_favorites($collection)) {
        json_response(400, ['error' => 'La colección Favoritos no se puede renombrar ni borrar']);
    }
    return $collection;
}

function clean_name($name): string
{
    $name = trim(preg_replace('/\s+/u', ' ', (string) $name));
    if ($name === '' || mb_strlen($name) > 80) {
        json_response(400, ['error' => 'El nombre debe tener entre 1 y 80 caracteres']);
    }
    return $name;
}

$user = current_user();

if ($_SERVER['REQUEST_METHOD'] === 'GET') {
    if (isset($_GET['id'])) {
        json_response(200, collection_payload(find_collection($_GET['id']), $user));
    }
    $user = require_user();
    ensure_favorites_collection($user);
    $stmt = db()->prepare("SELECT c.*, u.username AS owner FROM collections c JOIN users u ON u.id = c.user_id WHERE c.user_id = ? ORDER BY c.kind = 'favorites' DESC, c.name COLLATE NOCASE");
    $stmt->execute([$user['id']]);
    json_response(200, ['collections' => array_map(fn($c) => collection_payload($c, $user), $stmt->fetchAll())]);
}

require_post();
$user = require_user();
$input = json_input();

switch ($input['action'] ?? '') {
    case 'create':
        $name = clean_name($input['name'] ?? '');
        $count = db()->prepare("SELECT COUNT(*) FROM collections WHERE user_id = ? AND kind = 'custom'");
        $count->execute([$user['id']]);
        if ((int) $count->fetchColumn() >= MAX_COLLECTIONS_PER_USER) {
            json_response(400, ['error' => 'Has llegado al máximo de ' . MAX_COLLECTIONS_PER_USER . ' colecciones']);
        }
        $id = bin2hex(random_bytes(8));
        db()->prepare('INSERT INTO collections (id, user_id, name) VALUES (?, ?, ?)')->execute([$id, $user['id'], $name]);
        json_response(200, collection_payload(find_collection($id), $user));

    case 'rename':
        $collection = own_custom_collection($input['id'] ?? '', $user);
        db()->prepare('UPDATE collections SET name = ? WHERE id = ?')->execute([clean_name($input['name'] ?? ''), $collection['id']]);
        json_response(200, collection_payload(find_collection($collection['id']), $user));

    case 'delete':
        $collection = own_custom_collection($input['id'] ?? '', $user);
        db()->prepare('DELETE FROM collections WHERE id = ?')->execute([$collection['id']]);
        json_response(200, ['ok' => true]);

    case 'toggle':
        $collection = own_collection($input['id'] ?? '', $user);
        $paintingId = $input['painting_id'] ?? '';
        if (!valid_painting_id($paintingId)) {
            json_response(400, ['error' => 'Cuadro inválido']);
        }
        if (is_favorites($collection)) {
            $stmt = !empty($input['value'])
                ? db()->prepare('INSERT OR IGNORE INTO favorites (user_id, painting_id) SELECT ?, id FROM paintings WHERE id = ?')
                : db()->prepare('DELETE FROM favorites WHERE user_id = ? AND painting_id = ?');
            $stmt->execute([$user['id'], $paintingId]);
            json_response(200, ['ok' => true]);
        }
        $stmt = !empty($input['value'])
            ? db()->prepare('INSERT OR IGNORE INTO collection_paintings (collection_id, painting_id) SELECT ?, id FROM paintings WHERE id = ?')
            : db()->prepare('DELETE FROM collection_paintings WHERE collection_id = ? AND painting_id = ?');
        $stmt->execute([$collection['id'], $paintingId]);
        json_response(200, ['ok' => true]);

    default:
        json_response(400, ['error' => 'Acción desconocida']);
}
