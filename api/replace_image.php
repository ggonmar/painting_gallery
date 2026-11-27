<?php
// POST multipart {id, image} (superadmin): replace the image of a painting WITHOUT any AI processing.
// Only the file and its technical data (size, dimensions, orientation) change; the old image goes to data/trash/.
require __DIR__ . '/_common.php';

require_post();
require_admin();

$id = (string) ($_POST['id'] ?? '');
if (!valid_painting_id($id)) {
    json_response(400, ['error' => 'Cuadro inválido']);
}
$stmt = db()->prepare('SELECT * FROM paintings WHERE id = ?');
$stmt->execute([$id]);
$painting = $stmt->fetch();
if (!$painting) {
    json_response(404, ['error' => 'Cuadro no encontrado']);
}

$file = $_FILES['image'] ?? null;
if (!$file || is_array($file['error']) || $file['error'] !== UPLOAD_ERR_OK || !is_uploaded_file($file['tmp_name'])) {
    json_response(400, ['error' => 'No se recibió ninguna imagen']);
}
$info = @getimagesize($file['tmp_name']);
if ($info === false || !isset(IMAGE_TYPES[$info[2]])) {
    json_response(415, ['error' => 'El archivo no es una imagen soportada (jpg, png, webp, gif, bmp, tif)']);
}
[$width, $height] = $info;
$extension = IMAGE_TYPES[$info[2]];
$orientation = $width > $height ? 'landscape' : ($height > $width ? 'portrait' : 'square');

$paintingsRoot = realpath($PAINTINGS_DIR);
$oldPath = realpath($PAINTINGS_DIR . '/' . $painting['file_path']);
$oldInside = $oldPath && strpos($oldPath, $paintingsRoot . DIRECTORY_SEPARATOR) === 0;

// Same name as before, with the new extension and orientation ("... [landscape].jpg")
$base = pathinfo($painting['file_path'], PATHINFO_FILENAME);
$base = preg_replace('/\[(landscape|portrait|square)\]\s*$/', "[$orientation]", $base);
$newRelative = $base . '.' . $extension;
for ($n = 1; file_exists("$PAINTINGS_DIR/$newRelative") && realpath("$PAINTINGS_DIR/$newRelative") !== $oldPath; $n++) {
    $newRelative = "$base ($n).$extension";
}

// Old image -> trash (kept in case the new one is worse)
$trashedPath = null;
if ($oldInside && is_file($oldPath)) {
    $trashedPath = move_to_trash($oldPath, $painting['id'] . '__replaced_' . gmdate('Ymd-His') . '__' . basename($oldPath));
    if (!$trashedPath) {
        json_response(500, ['error' => 'No se pudo mover la imagen anterior a la papelera']);
    }
}
if (!move_uploaded_file($file['tmp_name'], "$PAINTINGS_DIR/$newRelative")) {
    if ($trashedPath) {
        @rename($trashedPath, $oldPath); // put the old image back
    }
    json_response(500, ['error' => 'No se pudo guardar la nueva imagen']);
}
@chmod("$PAINTINGS_DIR/$newRelative", 0664);

db()->prepare(
    'UPDATE paintings SET file_path = ?, file_size = ?, file_width = ?, file_height = ?, orientation = ?, updated_on_library = ? WHERE id = ?'
)->execute([
    $newRelative, filesize("$PAINTINGS_DIR/$newRelative"), $width, $height, $orientation,
    gmdate('Y-m-d\TH:i:s') . '+00:00', $painting['id'],
]);

// Refresh the JSON copy in the background
exec('setsid sh -c ' . shell_quote(engine_command(['tools/after_edit.py']) . ' > /dev/null 2>&1') . ' > /dev/null 2>&1 &');

json_response(200, ['ok' => true, 'file_path' => $newRelative, 'width' => $width, 'height' => $height, 'orientation' => $orientation]);
