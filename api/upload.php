<?php
// POST multipart (field "image"): stores the image in paintings/ and starts painting_renamer on it.
require __DIR__ . '/_common.php';

require_post();
$user = require_uploader();

$file = $_FILES['image'] ?? null;
if (!$file || is_array($file['error']) || $file['error'] !== UPLOAD_ERR_OK) {
    json_response(400, ['error' => 'No se recibió ninguna imagen (código ' . ($file['error'] ?? 'n/a') . ')']);
}
if (!is_uploaded_file($file['tmp_name'])) {
    json_response(400, ['error' => 'Subida inválida']);
}

$info = @getimagesize($file['tmp_name']);
if ($info === false || !isset(IMAGE_TYPES[$info[2]])) {
    json_response(415, ['error' => 'El archivo no es una imagen soportada (jpg, png, webp, gif, bmp, tif)']);
}
$extension = IMAGE_TYPES[$info[2]];

// Keep the original name (it is a useful hint for the AI) but make it filesystem/URL safe.
$base = pathinfo($file['name'] ?? '', PATHINFO_FILENAME);
$base = preg_replace('/[<>:"\/\\\\|?*#%\x00-\x1f]+/u', ' ', $base);
$base = trim(preg_replace('/\s+/u', ' ', $base), " .-");
if ($base === '') {
    $base = 'cuadro ' . date('Y-m-d His');
}
$base = mb_substr($base, 0, 150);

$target = "$PAINTINGS_DIR/$base.$extension";
for ($n = 1; file_exists($target); $n++) {
    $target = "$PAINTINGS_DIR/$base ($n).$extension";
}
if (!move_uploaded_file($file['tmp_name'], $target)) {
    json_response(500, ['error' => 'No se pudo guardar la imagen en el servidor']);
}
@chmod($target, 0664);

// Listed right away as "pending review" (only for users who can upload); the engine completes it.
// If the AI fails (quota, unknown painting...) it simply stays pending.
[$width, $height] = $info;
$paintingId = bin2hex(random_bytes(6));
$now = gmdate('Y-m-d\TH:i:s') . '+00:00';
db()->prepare(
    "INSERT INTO paintings (id, title, file_path, file_size, file_width, file_height, orientation, status, added_to_library, updated_on_library)
     VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)"
)->execute([
    $paintingId, $base, basename($target), filesize($target), $width, $height,
    $width > $height ? 'landscape' : ($height > $width ? 'portrait' : 'square'), $now, $now,
]);

$jobId = start_engine_job(['painting_renamer.py', $target], [
    'user_id' => (int) $user['id'],
    'painting_id' => $paintingId,
    'uploaded_name' => $file['name'],
    'stored_name' => basename($target),
]);

json_response(202, ['job' => $jobId, 'stored_name' => basename($target), 'painting_id' => $paintingId]);
