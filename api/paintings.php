<?php
// GET: all paintings with their descriptions (newest first), in the same shape the engine uses.
require __DIR__ . '/_common.php';

// Paintings pending review are only visible to users who can upload
$viewer = current_user();
$showPending = $viewer && can_upload($viewer);

const PAINTING_COLUMNS = [
    'id', 'title', 'original_title', 'artist', 'year', 'location', 'orientation', 'confidence_score',
    'confirmed', 'info_data_source', 'file_path', 'file_size', 'file_width', 'file_height',
    'added_to_library', 'updated_on_library', 'status',
];

$descriptions = [];
$rows = db()->query('SELECT * FROM descriptions ORDER BY painting_id, language, generated_at DESC, id ASC');
foreach ($rows as $row) {
    $descriptions[$row['painting_id']][$row['language']][] = [
        'description_id' => (int) $row['id'],
        'description' => $row['description'],
        'language' => $row['language'],
        'description_style' => $row['description_style'],
        'generated_at' => $row['generated_at'],
        'comment_creator' => $row['comment_creator'],
        'max_length' => $row['max_length'] === null ? null : (int) $row['max_length'],
    ];
}

$tags = [];
foreach (db()->query('SELECT painting_id, kind, tag FROM painting_tags ORDER BY painting_id, kind, position') as $row) {
    $tags[$row['painting_id']][$row['kind']][] = $row['tag'];
}

$geo = [];
foreach (db()->query("SELECT name, lat, lon, display_name, status FROM locations") as $row) {
    $geo[$row['name']] = $row;
}

$paintings = [];
$sql = 'SELECT * FROM paintings' . ($showPending ? '' : " WHERE status != 'pending'") . ' ORDER BY added_to_library, id';
foreach (db()->query($sql) as $row) {
    $painting = [];
    foreach (PAINTING_COLUMNS as $column) {
        $painting[$column] = $row[$column];
    }
    // Map position (geocoding cache filled by the engine); status null = not geocoded yet
    $location = $geo[$row['location'] ?? ''] ?? null;
    $painting['geo'] = $location ? [
        'status' => $location['status'],
        'lat' => $location['lat'] === null ? null : (float) $location['lat'],
        'lon' => $location['lon'] === null ? null : (float) $location['lon'],
        'place' => $location['display_name'],
    ] : null;
    $painting['confirmed'] = (bool) $row['confirmed'];
    foreach (['confidence_score'] as $column) {
        $painting[$column] = $row[$column] === null ? null : (float) $row[$column];
    }
    foreach (['file_size', 'file_width', 'file_height'] as $column) {
        $painting[$column] = $row[$column] === null ? null : (int) $row[$column];
    }
    $extra = $row['extra'] ? json_decode($row['extra'], true) : null;
    if (is_array($extra)) {
        $painting += $extra;
    }
    $painting['periods'] = $tags[$row['id']]['period'] ?? [];
    $painting['themes'] = $tags[$row['id']]['theme'] ?? [];
    $painting['descriptions'] = (object) ($descriptions[$row['id']] ?? []);
    $paintings[] = $painting;
}

purge_trash(); // housekeeping, at most once a day
json_response(200, ['paintings' => $paintings]);
