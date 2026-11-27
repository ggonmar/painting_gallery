<?php
// Serves index.html adding ?v=<mtime> to the local CSS/JS so browsers (and Cloudflare, which forces a 4h browser
// cache on static files) always load the versions that match this HTML.
$html = file_get_contents(__DIR__ . '/index.html');
$html = preg_replace_callback('/(href|src)="((?:css|js)\/[\w.-]+\.(?:css|js))"/', function ($m) {
    $mtime = @filemtime(__DIR__ . '/' . $m[2]);
    return $m[1] . '="' . $m[2] . ($mtime ? '?v=' . $mtime : '') . '"';
}, $html);
header('Content-Type: text/html; charset=UTF-8');
header('Cache-Control: no-cache');
echo $html;
