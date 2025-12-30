<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');

$baseDir = dirname(__DIR__) . DIRECTORY_SEPARATOR . 'data' . DIRECTORY_SEPARATOR . 'jjc_ranking_stats';

if (!is_dir($baseDir)) {
    http_response_code(404);
    echo json_encode(['error' => 'stats_dir_not_found', 'message' => '数据目录不存在']);
    exit;
}

$action = isset($_GET['action']) ? trim((string)$_GET['action']) : 'list';

if ($action === 'list') {
    $files = glob($baseDir . DIRECTORY_SEPARATOR . '*.json') ?: [];
    $timestamps = [];
    foreach ($files as $filePath) {
        $filename = basename($filePath, '.json');
        if (ctype_digit($filename)) {
            $timestamps[] = (int)$filename;
        }
    }
    rsort($timestamps);
    echo json_encode($timestamps, JSON_UNESCAPED_UNICODE);
    exit;
}

if ($action === 'read') {
    $timestamp = isset($_GET['timestamp']) ? trim((string)$_GET['timestamp']) : '';
    if ($timestamp === '' || !ctype_digit($timestamp)) {
        http_response_code(400);
        echo json_encode(['error' => 'invalid_timestamp', 'message' => 'timestamp 参数无效']);
        exit;
    }

    $filePath = $baseDir . DIRECTORY_SEPARATOR . $timestamp . '.json';
    if (!is_file($filePath)) {
        http_response_code(404);
        echo json_encode(['error' => 'not_found', 'message' => '未找到对应的统计文件']);
        exit;
    }

    $content = file_get_contents($filePath);
    if ($content === false) {
        http_response_code(500);
        echo json_encode(['error' => 'read_failed', 'message' => '读取统计文件失败']);
        exit;
    }

    echo $content;
    exit;
}

http_response_code(400);
echo json_encode(['error' => 'invalid_action', 'message' => 'action 参数无效']);
