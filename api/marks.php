<?php
// POST {type: seen|favorite, id, value: bool}       -> mark/unmark one painting
// POST {type: seen|favorite, ids: [...], value: true} -> mark several at once (import from the browser)
require __DIR__ . '/_common.php';

require_post();
$user = require_user();
$input = json_input();

$table = MARK_TABLES[$input['type'] ?? ''] ?? null;
if (!$table) {
    json_response(400, ['error' => 'Tipo de marca inválido']);
}

$ids = isset($input['ids']) && is_array($input['ids']) ? $input['ids'] : [$input['id'] ?? null];
$ids = array_values(array_unique(array_filter($ids, 'valid_painting_id')));
if (!$ids || count($ids) > 1000) {
    json_response(400, ['error' => 'Cuadro inválido']);
}

$stmt = !empty($input['value'])
    ? db()->prepare("INSERT OR IGNORE INTO $table (user_id, painting_id) SELECT ?, id FROM paintings WHERE id = ?")
    : db()->prepare("DELETE FROM $table WHERE user_id = ? AND painting_id = ?");

db()->beginTransaction();
foreach ($ids as $id) {
    $stmt->execute([$user['id'], $id]);
}
db()->commit();

json_response(200, ['ok' => true]);
