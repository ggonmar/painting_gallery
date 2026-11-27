<?php
// GET ?id=<job>: status of an upload processing job.
require __DIR__ . '/_common.php';
$user = require_user();

$id = $_GET['id'] ?? '';
if (!valid_job_id($id) || !is_dir("$JOBS_DIR/$id")) {
    json_response(404, ['error' => 'Trabajo no encontrado']);
}
$jobDir = "$JOBS_DIR/$id";
$meta = json_decode(@file_get_contents("$jobDir/meta.json") ?: '{}', true) ?: [];
if (!is_superadmin($user) && (int) ($meta['user_id'] ?? 0) !== (int) $user['id']) {
    json_response(404, ['error' => 'Trabajo no encontrado']);
}

$log = @file_get_contents("$jobDir/log.txt") ?: '';
$lines = array_values(array_filter(array_map('trim', preg_split('/\R/u', $log)), 'strlen'));
$exitCode = @file_get_contents("$jobDir/exit_code");
$result = json_decode(@file_get_contents("$jobDir/result.json") ?: 'null', true);

$state = 'processing';
$item = $result['results'][0] ?? null;
if ($exitCode !== false) {
    $state = (trim($exitCode) === '0' && $item && in_array($item['status'], ['processed', 'skipped_confirmed'], true))
        ? 'done'
        : 'failed';
}

json_response(200, [
    'state' => $state,
    'result' => $item,
    'daily_limit_reached' => $result['daily_limit_reached'] ?? false,
    'last_line' => end($lines) ?: '',
    'log' => $state === 'failed' ? implode("\n", array_slice($lines, -25)) : null,
]);
