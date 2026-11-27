<?php
// POST {id} (users who can upload): run the AI identification again on a painting pending review
// (e.g. after the Gemini daily quota resets). Poll the returned job with api/job.php.
require __DIR__ . '/_common.php';

require_post();
$user = require_uploader();
$input = json_input();

$id = (string) ($input['id'] ?? '');
if (!valid_painting_id($id)) {
    json_response(400, ['error' => 'Cuadro inválido']);
}
$stmt = db()->prepare('SELECT id, file_path, status FROM paintings WHERE id = ?');
$stmt->execute([$id]);
$painting = $stmt->fetch();
if (!$painting) {
    json_response(404, ['error' => 'Cuadro no encontrado']);
}
if ($painting['status'] !== 'pending') {
    json_response(400, ['error' => 'Este cuadro ya está revisado']);
}
$path = realpath($PAINTINGS_DIR . '/' . $painting['file_path']);
if (!$path || strpos($path, realpath($PAINTINGS_DIR) . DIRECTORY_SEPARATOR) !== 0 || !is_file($path)) {
    json_response(404, ['error' => 'No se encuentra la imagen del cuadro']);
}

$jobId = start_engine_job(['painting_renamer.py', $path], ['user_id' => (int) $user['id'], 'painting_id' => $id, 'reprocess' => true]);
json_response(202, ['job' => $jobId]);
