<?php
// AI used to process uploaded paintings (superadmin only). Stored in engine/ai_settings.json,
// which overrides config.json both here (engine_config) and in the Python engine (ConfigManager).
// GET  -> current choice + Ollama models available on the Ollama server
// POST {provider: gemini|ollama, ollama_model?}
require __DIR__ . '/_common.php';

require_admin();

const GEMINI_MODELS = ['gemini-2.5-flash-lite', 'gemini-2.5-flash', 'gemini-2.5-pro'];

function ollama_get(string $host, string $path, ?array $body = null): ?array
{
    $ch = curl_init(rtrim($host, '/') . $path);
    curl_setopt_array($ch, [CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 6, CURLOPT_CONNECTTIMEOUT => 3]);
    if ($body !== null) {
        curl_setopt_array($ch, [CURLOPT_POST => true, CURLOPT_POSTFIELDS => json_encode($body),
            CURLOPT_HTTPHEADER => ['Content-Type: application/json']]);
    }
    $response = curl_exec($ch);
    $ok = $response !== false && curl_getinfo($ch, CURLINFO_HTTP_CODE) === 200;
    curl_close($ch);
    return $ok ? json_decode($response, true) : null;
}

function ollama_models(string $host): ?array
{
    $tags = ollama_get($host, '/api/tags');
    if ($tags === null) {
        return null;
    }
    $models = [];
    foreach ($tags['models'] ?? [] as $m) {
        // Newer Ollama versions report capabilities; "vision" = the model can look at the image
        $show = ollama_get($host, '/api/show', ['model' => $m['name']]);
        $models[] = [
            'name' => $m['name'],
            'size' => $m['details']['parameter_size'] ?? '',
            'cloud' => str_ends_with($m['name'], ':cloud'),
            'vision' => in_array('vision', $show['capabilities'] ?? [], true),
        ];
    }
    usort($models, fn($a, $b) => strcmp($a['name'], $b['name']));
    return $models;
}

$config = engine_config();
$settingsFile = $ENGINE_DIR . '/ai_settings.json';

if ($_SERVER['REQUEST_METHOD'] === 'GET') {
    $sources = array_map('trim', explode(',', strtolower($config['data_source'] ?? 'gemini')));
    $models = ollama_models($config['ollama_host'] ?? '');
    json_response(200, [
        'provider' => in_array('ollama', $sources, true) && !in_array('gemini', $sources, true) ? 'ollama' : 'gemini',
        'gemini_model' => $config['gemini_model'] ?? '',
        'gemini_models' => array_values(array_unique(array_merge(GEMINI_MODELS, [$config['gemini_model'] ?? GEMINI_MODELS[0]]))),
        'ollama_model' => $config['ollama_model'] ?? '',
        'ollama_host' => $config['ollama_host'] ?? '',
        'ollama_reachable' => $models !== null,
        'ollama_models' => $models ?? [],
        'description_style' => $config['description_style'] ?? '',
        'description_max_length' => (int) ($config['description_max_length'] ?? 1000),
    ]);
}

require_post();
$input = json_input();
$provider = $input['provider'] ?? '';
$settings = json_decode(@file_get_contents($settingsFile) ?: '{}', true) ?: [];

if ($provider === 'gemini') {
    $model = (string) ($input['gemini_model'] ?? '');
    if (!in_array($model, GEMINI_MODELS, true) && $model !== ($config['gemini_model'] ?? '')) {
        json_response(400, ['error' => 'Modelo de Gemini no válido']);
    }
    $settings['data_source'] = 'gemini';
    $settings['gemini_model'] = $model;
} elseif ($provider === 'ollama') {
    $model = (string) ($input['ollama_model'] ?? '');
    $models = ollama_models($config['ollama_host'] ?? '');
    if ($models === null) {
        json_response(503, ['error' => 'No se puede conectar con Ollama (' . ($config['ollama_host'] ?? '?') . ')']);
    }
    if (!in_array($model, array_column($models, 'name'), true)) {
        json_response(400, ['error' => 'Ese modelo no está instalado en Ollama']);
    }
    $settings['data_source'] = 'ollama';
    $settings['ollama_model'] = $model;
} else {
    json_response(400, ['error' => 'IA no válida']);
}

if (array_key_exists('description_style', $input)) {
    $style = trim((string) $input['description_style']);
    if ($style === '' || mb_strlen($style) > 200) {
        json_response(400, ['error' => 'El estilo no puede estar vacío ni superar 200 caracteres']);
    }
    $settings['description_style'] = $style;
}
if (array_key_exists('description_max_length', $input)) {
    $maxLength = (int) $input['description_max_length'];
    if ($maxLength < 100 || $maxLength > 20000) {
        json_response(400, ['error' => 'La longitud máxima debe estar entre 100 y 20000 caracteres']);
    }
    $settings['description_max_length'] = $maxLength;
}

$settings['updated_at'] = gmdate('Y-m-d\TH:i:s') . '+00:00';
if (file_put_contents($settingsFile, json_encode($settings, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES) . "\n") === false) {
    json_response(500, ['error' => 'No se pudo guardar la configuración']);
}
@chmod($settingsFile, 0664);
json_response(200, ['ok' => true]);
