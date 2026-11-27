<?php
// Editing paintings from the web (only the admin user).
// GET                                     -> AI providers available for new descriptions
// POST {action: update, id, fields}       -> title, original_title, artist, year, location, confirmed
// POST {action: add_description, id, text}-> own description (new version, older ones are kept)
// POST {action: request_description, id, provider, style} -> background job (poll api/job.php)
// POST {action: update_description, id, description_id, text} -> fix the text of one version
// POST {action: delete_description, id, description_id}       -> remove one version
// POST {action: delete_painting, id} -> removes the painting (+ descriptions, seen, favorites);
//                                       the image is moved to data/trash/ (not served, not re-imported)
require __DIR__ . '/_common.php';

const EDITABLE_TEXT = ['title' => 300, 'original_title' => 300, 'artist' => 200, 'year' => 20, 'location' => 300];

function ai_providers(): array
{
    $config = engine_config();
    $providers = [];
    if (!empty($config['gemini_api_key'])) {
        $providers[] = ['id' => 'gemini', 'label' => 'Gemini (' . ($config['gemini_model'] ?? 'gemini') . ')'];
    }
    if (!empty($config['ollama_host'])) {
        $providers[] = ['id' => 'ollama', 'label' => 'Ollama (' . ($config['ollama_model'] ?? 'ollama') . ')'];
    }
    return $providers;
}

function tag_vocabulary(): array
{
    global $ENGINE_DIR;
    $vocabulary = json_decode(@file_get_contents($ENGINE_DIR . '/tags_vocabulary.json') ?: '', true);
    if (!is_array($vocabulary)) {
        json_response(500, ['error' => 'No se pudo leer engine/tags_vocabulary.json']);
    }
    return $vocabulary;
}

// Validate the tags chosen in the editor against the shared vocabulary and limits
function clean_tags($values, array $allowed, string $label): array
{
    if (!is_array($values)) {
        json_response(400, ['error' => "Formato de $label inválido"]);
    }
    $clean = [];
    foreach ($values as $value) {
        if (!in_array($value, $allowed, true)) {
            json_response(400, ['error' => "«$value» no es una $label válida"]);
        }
        if (!in_array($value, $clean, true)) {
            $clean[] = $value;
        }
    }
    return $clean;
}

function find_description(array $painting, $descriptionId): array
{
    $stmt = db()->prepare('SELECT * FROM descriptions WHERE id = ? AND painting_id = ?');
    $stmt->execute([(int) $descriptionId, $painting['id']]);
    $description = $stmt->fetch();
    if (!$description) {
        json_response(404, ['error' => 'Versión de la descripción no encontrada']);
    }
    return $description;
}

function find_painting(string $id): array
{
    if (!valid_painting_id($id)) {
        json_response(400, ['error' => 'Cuadro inválido']);
    }
    $stmt = db()->prepare('SELECT * FROM paintings WHERE id = ?');
    $stmt->execute([$id]);
    $painting = $stmt->fetch();
    if (!$painting) {
        json_response(404, ['error' => 'Cuadro no encontrado']);
    }
    return $painting;
}

// Geocode new locations (needed right away for the map) and refresh the JSON copy
function run_after_edit(bool $wait): void
{
    $cmd = engine_command(['tools/after_edit.py']) . ' > /dev/null 2>&1';
    if ($wait) {
        exec($cmd); // each Nominatim request has its own timeout
    } else {
        exec('setsid sh -c ' . shell_quote($cmd) . ' > /dev/null 2>&1 &');
    }
}

$admin = require_admin();

if ($_SERVER['REQUEST_METHOD'] === 'GET') {
    json_response(200, [
        'providers' => ai_providers(),
        'default_style' => engine_config()['description_style'] ?? '',
        'default_max_length' => (int) (engine_config()['description_max_length'] ?? 1000),
        'vocabulary' => tag_vocabulary(),
    ]);
}

require_post();
$input = json_input();
$painting = find_painting((string) ($input['id'] ?? ''));
$now = gmdate('Y-m-d\TH:i:s') . '+00:00'; // PHP's timezone on the NAS differs from the system one: store UTC explicitly

switch ($input['action'] ?? '') {
    case 'update':
        $fields = is_array($input['fields'] ?? null) ? $input['fields'] : [];
        $set = [];
        $values = [];
        foreach (EDITABLE_TEXT as $field => $maxLength) {
            if (!array_key_exists($field, $fields)) {
                continue;
            }
            $value = trim((string) $fields[$field]);
            if (mb_strlen($value) > $maxLength) {
                json_response(400, ['error' => "El campo $field es demasiado largo"]);
            }
            if ($field === 'title' && $value === '') {
                json_response(400, ['error' => 'El título no puede estar vacío']);
            }
            $set[] = "$field = ?";
            $values[] = $value;
        }
        if (array_key_exists('pending', $fields)) {
            $set[] = 'status = ?';
            $values[] = $fields['pending'] ? 'pending' : 'ready';
        }
        if (array_key_exists('confirmed', $fields)) {
            $set[] = 'confirmed = ?';
            $values[] = $fields['confirmed'] ? 1 : 0;
            // Confirmed entries are ground truth for the engine: full confidence
            if ($fields['confirmed']) {
                $set[] = 'confidence_score = 1.0';
            }
        }
        $tags = null;
        if (array_key_exists('periods', $fields) || array_key_exists('themes', $fields)) {
            $vocabulary = tag_vocabulary();
            $periods = clean_tags($fields['periods'] ?? [], $vocabulary['periods'], 'época');
            $themes = clean_tags($fields['themes'] ?? [], $vocabulary['themes'], 'temática');
            if (count($periods) > $vocabulary['max_periods']) {
                json_response(400, ['error' => 'Como máximo ' . $vocabulary['max_periods'] . ' épocas']);
            }
            if (count($periods) + count($themes) > $vocabulary['max_tags'] - 1) {
                json_response(400, ['error' => 'Como máximo ' . $vocabulary['max_tags'] . ' tags en total (incluido el formato)']);
            }
            $tags = ['period' => $periods, 'theme' => $themes];
        }
        if (!$set && $tags === null) {
            json_response(400, ['error' => 'No hay cambios']);
        }
        $set[] = 'updated_on_library = ?';
        $values[] = $now;
        $values[] = $painting['id'];
        db()->beginTransaction();
        db()->prepare('UPDATE paintings SET ' . implode(', ', $set) . ' WHERE id = ?')->execute($values);
        if ($tags !== null) {
            db()->prepare('DELETE FROM painting_tags WHERE painting_id = ?')->execute([$painting['id']]);
            $insert = db()->prepare('INSERT INTO painting_tags (painting_id, kind, tag, position) VALUES (?, ?, ?, ?)');
            foreach ($tags as $kind => $list) {
                foreach ($list as $position => $tag) {
                    $insert->execute([$painting['id'], $kind, $tag, $position]);
                }
            }
        }
        db()->commit();

        $newLocation = array_key_exists('location', $fields) ? trim((string) $fields['location']) : $painting['location'];
        $stmt = db()->prepare('SELECT 1 FROM locations WHERE name = ?');
        $stmt->execute([$newLocation]);
        run_after_edit($newLocation !== '' && !$stmt->fetchColumn());
        json_response(200, ['ok' => true]);

    case 'add_description':
        $text = trim((string) ($input['text'] ?? ''));
        if ($text === '' || mb_strlen($text) > 20000) {
            json_response(400, ['error' => 'La descripción está vacía o es demasiado larga']);
        }
        $user = current_user();
        $language = engine_config()['language'] ?? 'es';
        db()->prepare(
            'INSERT INTO descriptions (painting_id, language, description, description_style, generated_at, comment_creator, max_length) '
            . 'VALUES (?, ?, ?, ?, ?, ?, NULL)'
        )->execute([$painting['id'], $language, $text, 'manual', $now, $user['username'] . ' (manual)']);
        db()->prepare('UPDATE paintings SET updated_on_library = ? WHERE id = ?')->execute([$now, $painting['id']]);
        run_after_edit(false);
        json_response(200, ['ok' => true]);

    case 'request_description':
        $provider = (string) ($input['provider'] ?? '');
        if (!in_array($provider, array_column(ai_providers(), 'id'), true)) {
            json_response(400, ['error' => 'IA no disponible']);
        }
        $style = trim((string) ($input['style'] ?? ''));
        if (mb_strlen($style) > 200) {
            json_response(400, ['error' => 'El estilo es demasiado largo']);
        }
        $args = ['tools/generate_description.py', $painting['id'], $provider];
        if ($style !== '') {
            array_push($args, '--style', $style);
        }
        if (!empty($input['max_length'])) {
            $maxLength = (int) $input['max_length'];
            if ($maxLength < 100 || $maxLength > 20000) {
                json_response(400, ['error' => 'La longitud debe estar entre 100 y 20000 caracteres']);
            }
            array_push($args, '--max-length', (string) $maxLength);
        }
        $jobId = start_engine_job($args, ['user_id' => (int) $admin['id'], 'painting_id' => $painting['id'], 'provider' => $provider]);
        json_response(202, ['job' => $jobId]);

    case 'suggest_tags':
        // Only asks the processing AI (image + title/artist/year); the editor shows the result to review and save
        $jobId = start_engine_job(['tools/suggest_tags.py', $painting['id']], ['user_id' => (int) $admin['id'], 'painting_id' => $painting['id']]);
        json_response(202, ['job' => $jobId]);

    case 'update_description':
        $description = find_description($painting, $input['description_id'] ?? 0);
        $text = trim((string) ($input['text'] ?? ''));
        if ($text === '' || mb_strlen($text) > 50000) {
            json_response(400, ['error' => 'La descripción está vacía o es demasiado larga']);
        }
        try {
            db()->prepare('UPDATE descriptions SET description = ? WHERE id = ?')->execute([$text, $description['id']]);
        } catch (PDOException $e) {
            json_response(409, ['error' => 'Ya existe una versión idéntica de esta descripción']);
        }
        db()->prepare('UPDATE paintings SET updated_on_library = ? WHERE id = ?')->execute([$now, $painting['id']]);
        run_after_edit(false);
        json_response(200, ['ok' => true]);

    case 'delete_description':
        $description = find_description($painting, $input['description_id'] ?? 0);
        db()->prepare('DELETE FROM descriptions WHERE id = ?')->execute([$description['id']]);
        db()->prepare('UPDATE paintings SET updated_on_library = ? WHERE id = ?')->execute([$now, $painting['id']]);
        run_after_edit(false);
        json_response(200, ['ok' => true]);

    case 'delete_painting':
        // Move the image out of paintings/ first: otherwise the engine would import it again
        $image = realpath($PAINTINGS_DIR . '/' . $painting['file_path']);
        $trashed = null;
        if ($image && strpos($image, realpath($PAINTINGS_DIR) . DIRECTORY_SEPARATOR) === 0 && is_file($image)) {
            $trashed = $painting['id'] . '__' . basename($image);
            if (!move_to_trash($image, $trashed)) {
                json_response(500, ['error' => 'No se pudo mover la imagen a la papelera']);
            }
            // Keep the metadata next to it, so the painting can be restored by hand if needed
            $stmt = db()->prepare('SELECT * FROM descriptions WHERE painting_id = ?');
            $stmt->execute([$painting['id']]);
            file_put_contents(trash_dir() . "/$trashed.json", json_encode(
                ['painting' => $painting, 'descriptions' => $stmt->fetchAll(), 'deleted_at' => $now],
                JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT
            ));
        }
        // ON DELETE CASCADE removes its descriptions, seen and favorites
        db()->prepare('DELETE FROM paintings WHERE id = ?')->execute([$painting['id']]);
        run_after_edit(false);
        json_response(200, ['ok' => true, 'trashed_as' => $trashed]);

    default:
        json_response(400, ['error' => 'Acción desconocida']);
}
