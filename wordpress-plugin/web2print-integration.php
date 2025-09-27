<?php
/**
 * Plugin Name: Web2Print WooCommerce Integration
 * Plugin URI: https://github.com/web2print/integration
 * Description: Integração avançada para cálculo de custos de impressão com análise de PDF e configuração personalizada
 * Version: 1.0.0
 * Author: Web2Print Team
 * License: GPL v2 or later
 * Text Domain: web2print-integration
 */

// Prevenir acesso direto
if (!defined('ABSPATH')) {
    exit;
}

// Definir constantes do plugin
define('WEB2PRINT_PLUGIN_URL', plugin_dir_url(__FILE__));
define('WEB2PRINT_PLUGIN_PATH', plugin_dir_path(__FILE__));
define('WEB2PRINT_VERSION', '1.0.0');

class Web2PrintIntegration {
    
    private $api_endpoint;
    private $api_key;
    
    public function __construct() {
        $this->api_endpoint = get_option('web2print_api_endpoint', '');
        $this->api_key = get_option('web2print_api_key', '');
        
        add_action('init', array($this, 'init'));
        add_action('wp_enqueue_scripts', array($this, 'enqueue_scripts'));
        add_action('wp_ajax_web2print_calculate', array($this, 'ajax_calculate_cost'));
        add_action('wp_ajax_nopriv_web2print_calculate', array($this, 'ajax_calculate_cost'));
        add_action('wp_ajax_web2print_upload_pdf', array($this, 'ajax_upload_pdf'));
        add_action('wp_ajax_nopriv_web2print_upload_pdf', array($this, 'ajax_upload_pdf'));
        add_action('woocommerce_before_calculate_totals', array($this, 'force_calculated_price'));
        add_action('woocommerce_add_to_cart', array($this, 'save_print_metadata'), 10, 6);
        add_action('admin_menu', array($this, 'admin_menu'));
        
        // CRÍTICO: Validação obrigatória antes de adicionar ao carrinho
        add_filter('woocommerce_add_to_cart_validation', array($this, 'validate_add_to_cart'), 10, 3);
        
        // Hooks para exibir metadados no carrinho e checkout
        add_filter('woocommerce_get_item_data', array($this, 'display_cart_item_data'), 10, 2);
        add_action('woocommerce_checkout_create_order_line_item', array($this, 'save_order_item_meta'), 10, 4);
        
        // Hook para adicionar campos personalizados no produto
        add_action('woocommerce_single_product_summary', array($this, 'add_print_calculator'), 25);
        
        // DISPLAY NO PAINEL ADMINISTRATIVO PARA PRODUÇÃO
        add_action('admin_enqueue_scripts', array($this, 'admin_enqueue_scripts'));
        add_action('woocommerce_admin_order_item_values', array($this, 'display_web2print_order_details'), 10, 3);
        add_action('wp_ajax_web2print_download_pdf', array($this, 'secure_pdf_download'));
        
        // SISTEMA DE MONITORAMENTO DA API
        add_action('wp', array($this, 'schedule_api_monitoring'));
        add_action('web2print_monitor_api', array($this, 'monitor_api_health'));
        add_action('admin_notices', array($this, 'display_api_status_notices'));
        add_filter('woocommerce_add_to_cart_validation', array($this, 'check_api_before_add_to_cart'), 5, 3);
        
        // AJAX para testes e gerenciamento
        add_action('wp_ajax_web2print_test_api_now', array($this, 'ajax_test_api_now'));
        add_action('wp_ajax_web2print_clear_metrics', array($this, 'ajax_clear_metrics'));
        add_action('wp_ajax_web2print_send_test_alert', array($this, 'ajax_send_test_alert'));
    }
    
    public function init() {
        // Carregar texto do domínio
        load_plugin_textdomain('web2print-integration', false, dirname(plugin_basename(__FILE__)) . '/languages/');
        
        // Inicializar configurações padrão de alertas
        $this->init_alert_settings();
    }
    
    /**
     * Inicializar configurações padrão de alertas
     */
    private function init_alert_settings() {
        if (get_option('web2print_alert_email') === false) {
            update_option('web2print_alert_email', get_option('admin_email'));
        }
        if (get_option('web2print_slow_threshold') === false) {
            update_option('web2print_slow_threshold', 5000); // 5 segundos
        }
        if (get_option('web2print_email_alerts') === false) {
            update_option('web2print_email_alerts', true);
        }
        if (get_option('web2print_check_interval') === false) {
            update_option('web2print_check_interval', 5); // 5 minutos
        }
    }
    
    public function enqueue_scripts() {
        if (is_product() || is_cart()) {
            wp_enqueue_script(
                'web2print-ajax',
                WEB2PRINT_PLUGIN_URL . 'js/web2print-ajax.js',
                array('jquery'),
                WEB2PRINT_VERSION,
                true
            );
            
            wp_localize_script('web2print-ajax', 'web2print_ajax', array(
                'ajax_url' => admin_url('admin-ajax.php'),
                'nonce' => wp_create_nonce('web2print_nonce'),
                'api_endpoint' => $this->api_endpoint,
                'texts' => array(
                    'calculating' => __('Calculando...', 'web2print-integration'),
                    'error' => __('Erro ao calcular. Tente novamente.', 'web2print-integration'),
                    'invalid_file' => __('Formato inválido. Apenas PDFs são aceitos.', 'web2print-integration'),
                    'file_too_large' => __('Arquivo muito grande. Máximo 50MB.', 'web2print-integration'),
                    'upload_error' => __('Erro no upload. Tente novamente.', 'web2print-integration')
                )
            ));
            
            wp_enqueue_style(
                'web2print-style',
                WEB2PRINT_PLUGIN_URL . 'css/web2print-style.css',
                array(),
                WEB2PRINT_VERSION
            );
        }
    }
    
    public function add_print_calculator() {
        global $product;
        
        // Verificar se o produto é do tipo "impressão personalizada"
        if ($product && $product->get_meta('_enable_web2print') === 'yes') {
            include WEB2PRINT_PLUGIN_PATH . 'templates/calculator-form.php';
        }
    }
    
    public function ajax_calculate_cost() {
        // Verificar nonce
        if (!isset($_POST['nonce']) || !wp_verify_nonce($_POST['nonce'], 'web2print_nonce')) {
            wp_die(__('Falha na verificação de segurança', 'web2print-integration'));
        }
        
        // VALIDAÇÃO CRÍTICA: Verificar se existe análise de PDF válida na sessão
        $pdf_analysis = WC()->session->get('web2print_pdf_analysis');
        if (!$pdf_analysis || !isset($pdf_analysis['verified']) || !$pdf_analysis['verified']) {
            wp_send_json_error(array(
                'message' => __('PDF não foi analisado corretamente. Faça upload novamente.', 'web2print-integration')
            ));
            return;
        }
        
        // Usar dados VALIDADOS da análise de PDF (não do cliente!)
        $color_pages = intval($pdf_analysis['color_pages']);
        $mono_pages = intval($pdf_analysis['mono_pages']);
        $paper_type = sanitize_text_field($_POST['paper_type']);
        $paper_weight = intval($_POST['paper_weight']);
        $binding_type = sanitize_text_field($_POST['binding_type']);
        $finishing = isset($_POST['finishing']) ? sanitize_text_field($_POST['finishing']) : '';
        $copy_quantity = isset($_POST['copy_quantity']) ? intval($_POST['copy_quantity']) : 1;
        
        // Preparar dados para API
        $api_data = array(
            'color_pages' => $color_pages,
            'mono_pages' => $mono_pages,
            'paper_type' => $paper_type,
            'paper_weight' => $paper_weight,
            'binding_type' => $binding_type,
            'finishing' => $finishing,
            'copy_quantity' => $copy_quantity
        );
        
        // Fazer chamada para API
        $response = $this->call_api($api_data);
        
        if ($response && $response['success']) {
            // Adicionar token de verificação ao cálculo
            $response['verification_token'] = $pdf_analysis['verification_token'];
            
            // Salvar dados na sessão para uso posterior
            WC()->session->set('web2print_calculation', $response);
            WC()->session->set('web2print_config', $api_data);
            
            wp_send_json_success($response);
        } else {
            wp_send_json_error(array(
                'message' => __('Erro ao calcular custos', 'web2print-integration')
            ));
        }
    }
    
    private function call_api($data) {
        if (empty($this->api_endpoint) || empty($this->api_key)) {
            error_log('Web2Print: API endpoint ou key não configurados');
            return false;
        }
        
        // FASE 1: Timeout otimizado baseado no tamanho dos dados
        $estimated_size = strlen(json_encode($data));
        $timeout = ($estimated_size > 1000) ? 25 : 15; // Timeout dinâmico
        
        $args = array(
            'method' => 'POST',
            'timeout' => $timeout, // Otimizado da Fase 1
            'headers' => array(
                'Content-Type' => 'application/json',
                'X-API-Key' => $this->api_key,
                'User-Agent' => 'Web2Print-Plugin/1.0'
            ),
            'body' => json_encode($data)
        );
        
        $response = wp_remote_post($this->api_endpoint, $args);
        
        if (is_wp_error($response)) {
            error_log('Web2Print API Error: ' . $response->get_error_message());
            return false;
        }
        
        $body = wp_remote_retrieve_body($response);
        $data = json_decode($body, true);
        
        if (wp_remote_retrieve_response_code($response) !== 200) {
            error_log('Web2Print API HTTP Error: ' . wp_remote_retrieve_response_code($response));
            return false;
        }
        
        return $data;
    }
    
    /**
     * Validação robusta de arquivo PDF - server-side
     */
    private function validate_pdf_file_robust($file) {
        // 1. Verificar extensão e MIME type
        $file_info = wp_check_filetype_and_ext($file['tmp_name'], $file['name'], array('pdf' => 'application/pdf'));
        
        if (!$file_info['type'] || $file_info['type'] !== 'application/pdf') {
            return __('Formato inválido. Apenas PDFs são aceitos.', 'web2print-integration');
        }
        
        // 2. Verificar magic bytes (assinatura do PDF)
        $file_content = file_get_contents($file['tmp_name'], false, null, 0, 5);
        if (!$file_content || substr($file_content, 0, 4) !== '%PDF') {
            return __('Formato inválido. Apenas PDFs são aceitos.', 'web2print-integration');
        }
        
        // 3. Verificar tamanho máximo (50MB para consistência com cliente)
        $max_size = 50 * 1024 * 1024; // 50MB
        if ($file['size'] > $max_size) {
            return __('Arquivo muito grande. Máximo 50MB.', 'web2print-integration');
        }
        
        // 4. Verificar tamanho mínimo (pelo menos 1KB)
        if ($file['size'] < 1024) {
            return __('Formato inválido. Apenas PDFs são aceitos.', 'web2print-integration');
        }
        
        // 5. Verificar se arquivo não está corrompido (tentativa básica de abertura)
        $temp_handle = fopen($file['tmp_name'], 'rb');
        if (!$temp_handle) {
            return __('Formato inválido. Apenas PDFs são aceitos.', 'web2print-integration');
        }
        
        // Verificar se consegue ler os primeiros 100 bytes
        $header = fread($temp_handle, 100);
        fclose($temp_handle);
        
        if (strlen($header) < 10) {
            return __('Formato inválido. Apenas PDFs são aceitos.', 'web2print-integration');
        }
        
        return null; // Arquivo válido
    }
    
    public function ajax_upload_pdf() {
        // Verificar nonce
        if (!isset($_POST['nonce']) || !wp_verify_nonce($_POST['nonce'], 'web2print_nonce')) {
            wp_die(__('Falha na verificação de segurança', 'web2print-integration'));
        }
        
        // Verificar se arquivo foi enviado
        if (!isset($_FILES['pdf_file']) || $_FILES['pdf_file']['error'] !== UPLOAD_ERR_OK) {
            wp_send_json_error(array(
                'message' => __('Erro no upload do arquivo', 'web2print-integration')
            ));
            return;
        }
        
        $file = $_FILES['pdf_file'];
        
        // VALIDAÇÃO ROBUSTA SERVER-SIDE
        $validation_error = $this->validate_pdf_file_robust($file);
        if ($validation_error) {
            wp_send_json_error(array(
                'message' => $validation_error
            ));
            return;
        }
        
        try {
            // CRÍTICO: SALVAR ARQUIVO PERMANENTEMENTE no WordPress
            // Configurar wp_handle_upload() para salvar PDF
            if (!function_exists('wp_handle_upload')) {
                require_once(ABSPATH . 'wp-admin/includes/file.php');
            }
            
            $upload_overrides = array(
                'test_form' => false,
                'mimes' => array('pdf' => 'application/pdf'),
                'upload_error_handler' => '__return_false'
            );
            
            // Mover arquivo para o diretório de uploads do WordPress  
            $uploaded_file = wp_handle_upload($file, $upload_overrides);
            
            if (isset($uploaded_file['error'])) {
                wp_send_json_error(array(
                    'message' => __('Erro ao salvar arquivo: ', 'web2print-integration') . $uploaded_file['error']
                ));
                return;
            }
            
            // ANÁLISE PRECISA VIA FLASK API (PyMuPDF)
            // Enviar URL do arquivo salvo para análise centralizada no Flask
            $flask_analysis = $this->analyze_pdf_via_flask($uploaded_file['url']);
            
            if (!$flask_analysis) {
                wp_send_json_error(array(
                    'message' => __('Erro na análise do PDF. Tente novamente.', 'web2print-integration')
                ));
                return;
            }
            
            // Usar dados precisos retornados pelo Flask
            $page_count = $flask_analysis['total_pages'];
            $color_pages = $flask_analysis['color_pages'];
            $mono_pages = $flask_analysis['mono_pages'];
            
            // Hash local para consistência
            $pdf_content = file_get_contents($uploaded_file['file']);
            $content_hash = md5($pdf_content);
            
            // Gerar token de verificação criptográfico
            $verification_token = wp_generate_password(32, false);
            
            // CRÍTICO: Salvar dados completos da análise na sessão
            $analysis = array(
                'total_pages' => $page_count,
                'color_pages' => $color_pages,
                'mono_pages' => $mono_pages,
                'filename' => sanitize_file_name($file['name']),
                'filesize' => $file['size'],
                'content_hash' => $content_hash,
                'file_url' => $uploaded_file['url'], // CRÍTICO: URL para acesso da gráfica
                'file_path' => $uploaded_file['file'], // Caminho completo no servidor
                'verified' => true, // CRÍTICO: marca como verificado pelo servidor
                'verification_token' => $verification_token,
                'timestamp' => time(),
                'analysis_method' => $flask_analysis['analysis_method'] ?? 'flask_analysis'
            );
            
            WC()->session->set('web2print_pdf_analysis', $analysis);
            
            wp_send_json_success($analysis);
            
        } catch (Exception $e) {
            wp_send_json_error(array(
                'message' => __('Erro ao analisar PDF', 'web2print-integration')
            ));
        }
    }
    
    private function analyze_pdf_via_flask($pdf_url) {
        // CRÍTICO: Análise centralizada via Flask API com PyMuPDF + SISTEMA ASSÍNCRONO
        if (empty($this->api_endpoint) || empty($this->api_key)) {
            error_log('Web2Print: API endpoint ou key não configurados para análise');
            return false;
        }
        
        // Preparar URL da rota de análise
        $analyze_url = rtrim($this->api_endpoint, '/') . '/analyze_pdf_url';
        
        // FASE 1: Verificação rápida de tamanho antes da análise
        $head_response = wp_remote_head($pdf_url, array('timeout' => 5));
        $file_size = 0;
        if (!is_wp_error($head_response)) {
            $content_length = wp_remote_retrieve_header($head_response, 'content-length');
            $file_size = $content_length ? intval($content_length) : 0;
        }
        
        // Timeout dinâmico baseado no tamanho (Fase 1)
        $timeout = 30; // Default
        if ($file_size > 0) {
            if ($file_size <= 10 * 1024 * 1024) { // <= 10MB
                $timeout = 20;
            } elseif ($file_size <= 25 * 1024 * 1024) { // <= 25MB
                $timeout = 35;
            } else { // > 25MB
                $timeout = 50;
            }
        }
        
        error_log(sprintf('Web2Print: Iniciando análise PDF - Tamanho: %s, Timeout: %ds', 
            $file_size ? size_format($file_size) : 'desconhecido', $timeout));
        
        $args = array(
            'method' => 'POST',
            'timeout' => $timeout, // Timeout otimizado da Fase 1
            'headers' => array(
                'Content-Type' => 'application/json',
                'X-API-Key' => $this->api_key,
                'User-Agent' => 'Web2Print-Analyzer/1.0'
            ),
            'body' => json_encode(array(
                'pdf_url' => $pdf_url,
                'file_size_hint' => $file_size
            ))
        );
        
        $response = wp_remote_post($analyze_url, $args);
        
        if (is_wp_error($response)) {
            error_log('Web2Print Flask Analysis Error: ' . $response->get_error_message());
            return false;
        }
        
        $body = wp_remote_retrieve_body($response);
        $data = json_decode($body, true);
        $response_code = wp_remote_retrieve_response_code($response);
        
        // PRIORIDADE 1: SUPORTE ASSÍNCRONO - TRATAR TANTO 200 (SYNC) QUANTO 202 (ASYNC)
        if ($response_code === 200) {
            // Processamento síncrono - resposta imediata
            if (!$data['success']) {
                error_log('Web2Print Flask Analysis API Error: ' . $data['error']);
                return false;
            }
            error_log('Web2Print: Análise síncrona concluída em ' . $data['data']['processing_time_seconds'] . 's');
            return $data['data'];
            
        } elseif ($response_code === 202) {
            // Processamento assíncrono - fazer polling
            if (!isset($data['job_id'])) {
                error_log('Web2Print: Resposta 202 sem job_id');
                return false;
            }
            
            $job_id = $data['job_id'];
            $estimated_time = isset($data['estimated_time_seconds']) ? $data['estimated_time_seconds'] : 60;
            
            error_log(sprintf('Web2Print: Análise assíncrona iniciada - Job: %s, ETA: %ds', $job_id, $estimated_time));
            
            // Fazer polling até conclusão
            return $this->poll_job_until_completion($job_id, $estimated_time);
            
        } else {
            error_log('Web2Print Flask Analysis HTTP Error: ' . $response_code);
            error_log('Response body: ' . $body);
            return false;
        }
        
        // Retornar dados da análise precisos do Flask
        return $data['data'];
    }
    
    /**
     * PRIORIDADE 1: POLLING PARA JOBS ASSÍNCRONOS
     */
    private function poll_job_until_completion($job_id, $estimated_time_seconds) {
        $polling_url = rtrim($this->api_endpoint, '/') . '/jobs/' . $job_id;
        
        // Configuração de polling exponential backoff
        $max_attempts = 30; // Máximo 30 tentativas
        $initial_interval = 2; // Começar com 2 segundos
        $max_interval = 10; // Máximo 10 segundos entre tentativas
        $timeout_total = max($estimated_time_seconds + 30, 120); // Pelo menos 2 minutos total
        
        $start_time = time();
        $interval = $initial_interval;
        
        error_log(sprintf('Web2Print: Iniciando polling para job %s - Max %d tentativas, timeout %ds', 
            $job_id, $max_attempts, $timeout_total));
        
        for ($attempt = 1; $attempt <= $max_attempts; $attempt++) {
            // Verificar timeout total
            if (time() - $start_time > $timeout_total) {
                error_log(sprintf('Web2Print: Timeout total atingido para job %s após %ds', 
                    $job_id, time() - $start_time));
                return false;
            }
            
            // Fazer requisição de polling
            $response = wp_remote_get($polling_url, array(
                'timeout' => 10,
                'headers' => array(
                    'X-API-Key' => $this->api_key,
                    'User-Agent' => 'Web2Print-Polling/1.0'
                )
            ));
            
            if (is_wp_error($response)) {
                error_log(sprintf('Web2Print: Erro no polling (tentativa %d): %s', 
                    $attempt, $response->get_error_message()));
                
                // Aguardar antes de tentar novamente
                sleep($interval);
                $interval = min($interval * 1.5, $max_interval); // Exponential backoff
                continue;
            }
            
            $body = wp_remote_retrieve_body($response);
            $data = json_decode($body, true);
            $response_code = wp_remote_retrieve_response_code($response);
            
            if ($response_code === 404) {
                error_log('Web2Print: Job não encontrado: ' . $job_id);
                return false;
            }
            
            if ($response_code === 410) {
                error_log('Web2Print: Job expirado: ' . $job_id);
                return false;
            }
            
            if ($response_code !== 200) {
                error_log(sprintf('Web2Print: Erro HTTP no polling: %d - %s', $response_code, $body));
                sleep($interval);
                continue;
            }
            
            $status = isset($data['status']) ? $data['status'] : 'unknown';
            $progress = isset($data['progress']) ? $data['progress'] : 0;
            
            error_log(sprintf('Web2Print: Job %s - Status: %s, Progresso: %d%% (tentativa %d)', 
                $job_id, $status, $progress, $attempt));
            
            if ($status === 'completed') {
                // Job concluído com sucesso
                if (isset($data['data'])) {
                    $processing_time = time() - $start_time;
                    error_log(sprintf('Web2Print: Job %s CONCLUÍDO em %ds total', $job_id, $processing_time));
                    return $data['data'];
                } else {
                    error_log('Web2Print: Job completed sem dados de resultado');
                    return false;
                }
                
            } elseif ($status === 'failed') {
                // Job falhou
                $error = isset($data['error']) ? $data['error'] : 'Erro desconhecido';
                error_log('Web2Print: Job falhou: ' . $error);
                return false;
                
            } elseif ($status === 'pending' || $status === 'running') {
                // Job ainda em processamento, continuar polling
                sleep($interval);
                
                // Ajustar intervalo baseado no progresso
                if ($progress > 50) {
                    $interval = min($interval, 3); // Mais frequente quando próximo da conclusão
                } else {
                    $interval = min($interval * 1.2, $max_interval); // Menos frequente no início
                }
                continue;
                
            } else {
                error_log('Web2Print: Status de job desconhecido: ' . $status);
                sleep($interval);
                continue;
            }
        }
        
        error_log(sprintf('Web2Print: Polling esgotado para job %s após %d tentativas', 
            $job_id, $max_attempts));
        return false;
    }
    
    private function count_pdf_pages($pdf_content) {
        // DEPRECATED: Método básico mantido como fallback
        // Análise agora é feita via Flask/PyMuPDF para precisão
        preg_match_all('/\/Page\W/', $pdf_content, $matches);
        $page_count = count($matches[0]);
        
        // Fallback se não conseguir detectar
        if ($page_count == 0) {
            preg_match_all('/\/Count\s+(\d+)/', $pdf_content, $matches);
            if (isset($matches[1][0])) {
                $page_count = intval($matches[1][0]);
            }
        }
        
        return max(1, $page_count); // Mínimo 1 página
    }
    
    public function force_calculated_price($cart) {
        if (is_admin() && !defined('DOING_AJAX')) return;
        
        foreach ($cart->get_cart() as $cart_item_key => $cart_item) {
            if (isset($cart_item['web2print_cost_per_unit'])) {
                // Definir preço por unidade (não total)
                $cart_item['data']->set_price($cart_item['web2print_cost_per_unit']);
            }
        }
    }
    
    public function save_print_metadata($cart_item_key, $product_id, $quantity, $variation_id, $variation, $cart_item_data) {
        $calculation = WC()->session->get('web2print_calculation');
        $config = WC()->session->get('web2print_config');
        $pdf_analysis = WC()->session->get('web2print_pdf_analysis');
        
        if ($calculation && $config && $pdf_analysis) {
            // Salvar preço POR UNIDADE (cost_per_copy) não o total
            WC()->cart->cart_contents[$cart_item_key]['web2print_cost_per_unit'] = $calculation['cost_details']['cost_per_copy'];
            WC()->cart->cart_contents[$cart_item_key]['web2print_data'] = array(
                'calculation' => $calculation,
                'config' => $config,
                // DADOS COMPLETOS DO PDF PARA GRÁFICA
                'pdf_file_url' => $pdf_analysis['file_url'], // CRÍTICO: URL do arquivo para gráfica
                'pdf_file_path' => $pdf_analysis['file_path'] ?? '', // Caminho local como fallback
                'pdf_filename' => $pdf_analysis['filename'],
                'pdf_filesize' => $pdf_analysis['filesize'],
                'content_hash' => $pdf_analysis['content_hash'] ?? '',
                'verification_token' => $pdf_analysis['verification_token'] ?? '',
                'analysis_method' => $pdf_analysis['analysis_method'] ?? 'unknown',
                'verified' => $pdf_analysis['verified'] ?? false,
                'timestamp' => current_time('mysql'),
                'upload_timestamp' => $pdf_analysis['timestamp'] ?? time()
            );
            
            // Log da passagem de dados para carrinho
            error_log(sprintf(
                'Web2Print: Dados PDF salvos no carrinho. URL: %s, Hash: %s, Token: %s',
                $pdf_analysis['file_url'] ?? 'N/A',
                substr($pdf_analysis['content_hash'] ?? '', 0, 8),
                substr($pdf_analysis['verification_token'] ?? '', 0, 8)
            ));
            
            // Limpar dados da sessão
            WC()->session->__unset('web2print_calculation');
            WC()->session->__unset('web2print_config');
            WC()->session->__unset('web2print_pdf_analysis');
        }
    }
    
    public function validate_add_to_cart($passed, $product_id, $quantity) {
        $product = wc_get_product($product_id);
        
        // Verificar se o produto requer Web2Print
        if ($product && $product->get_meta('_enable_web2print') === 'yes') {
            // Verificar se existe cálculo válido na sessão
            $calculation = WC()->session->get('web2print_calculation');
            $config = WC()->session->get('web2print_config');
            $pdf_analysis = WC()->session->get('web2print_pdf_analysis');
            
            if (!$calculation || !$config || !$pdf_analysis) {
                wc_add_notice(__('Você deve configurar a impressão e fazer upload do PDF antes de adicionar ao carrinho.', 'web2print-integration'), 'error');
                return false;
            }
            
            // Verificar token de verificação
            if (!isset($calculation['verification_token']) || 
                !isset($pdf_analysis['verification_token']) ||
                $calculation['verification_token'] !== $pdf_analysis['verification_token']) {
                wc_add_notice(__('Dados de impressão inválidos. Faça upload do PDF novamente.', 'web2print-integration'), 'error');
                return false;
            }
            
            // Verificar se análise não expirou (máximo 30 minutos)
            if ((time() - $pdf_analysis['timestamp']) > 1800) {
                wc_add_notice(__('Análise do PDF expirou. Faça upload novamente.', 'web2print-integration'), 'error');
                return false;
            }
        }
        
        return $passed;
    }
    
    public function display_cart_item_data($item_data, $cart_item) {
        if (isset($cart_item['web2print_data'])) {
            $data = $cart_item['web2print_data'];
            $config = $data['config'];
            $calculation = $data['calculation'];
            
            $item_data[] = array(
                'name' => __('📄 Configuração de Impressão', 'web2print-integration'),
                'value' => sprintf(
                    '%s | %s | %d cópias',
                    esc_html($calculation['breakdown']['paper_info']),
                    esc_html($calculation['breakdown']['binding_info']),
                    intval($config['copy_quantity'])
                )
            );
            
            if (!empty($calculation['breakdown']['finishing_info'])) {
                $item_data[] = array(
                    'name' => __('✨ Acabamentos', 'web2print-integration'),
                    'value' => esc_html($calculation['breakdown']['finishing_info'])
                );
            }
            
            $item_data[] = array(
                'name' => __('📊 Páginas Analisadas', 'web2print-integration'),
                'value' => sprintf(
                    '%d coloridas + %d monocromáticas = %d total',
                    $calculation['breakdown']['color_pages'],
                    $calculation['breakdown']['mono_pages'],
                    $calculation['breakdown']['total_pages']
                )
            );
        }
        
        return $item_data;
    }
    
    public function save_order_item_meta($item, $cart_item_key, $values, $order) {
        if (isset($values['web2print_data'])) {
            $data = $values['web2print_data'];
            
            // Log início do processo
            error_log(sprintf(
                'Web2Print: Salvando metadados do pedido #%d, item #%d',
                $order->get_id(),
                $item->get_id()
            ));
            
            // Salvar dados essenciais como meta do item do pedido
            $item->add_meta_data('_web2print_config', $data['config']);
            $item->add_meta_data('_web2print_calculation', $data['calculation']);
            $item->add_meta_data('_web2print_timestamp', $data['timestamp']);
            
            // CRÍTICO: Validação e salvamento robusta do URL do PDF
            if (isset($data['pdf_file_url']) && !empty($data['pdf_file_url'])) {
                $pdf_url = $data['pdf_file_url'];
                
                // 1. VALIDAÇÃO DO URL
                if (filter_var($pdf_url, FILTER_VALIDATE_URL)) {
                    // Verificar se URL é acessível
                    $response = wp_remote_head($pdf_url, array('timeout' => 10));
                    $is_accessible = !is_wp_error($response) && wp_remote_retrieve_response_code($response) === 200;
                    
                    // Salvar URL validado e status de verificação
                    $item->add_meta_data('_web2print_pdf_url', $pdf_url);
                    $item->add_meta_data('_web2print_pdf_url_verified', $is_accessible ? 'yes' : 'no');
                    $item->add_meta_data('_web2print_pdf_url_checked_at', current_time('mysql'));
                    
                    // 2. DADOS ESSENCIAIS PARA GRÁFICA
                    $item->add_meta_data('_web2print_pdf_filename', $data['pdf_filename'] ?? '');
                    $item->add_meta_data('_web2print_pdf_filesize', $data['pdf_filesize'] ?? 0);
                    
                    // 3. METADADOS DE VERIFICAÇÃO E FALLBACK
                    if (isset($data['pdf_file_path'])) {
                        $item->add_meta_data('_web2print_pdf_local_path', $data['pdf_file_path']);
                    }
                    
                    if (isset($data['content_hash'])) {
                        $item->add_meta_data('_web2print_pdf_hash', $data['content_hash']);
                    }
                    
                    if (isset($data['verification_token'])) {
                        $item->add_meta_data('_web2print_verification_token', $data['verification_token']);
                    }
                    
                    // 4. METADADOS TÉCNICOS
                    $item->add_meta_data('_web2print_analysis_method', $data['analysis_method'] ?? 'unknown');
                    $item->add_meta_data('_web2print_upload_timestamp', $data['upload_timestamp'] ?? '');
                    $item->add_meta_data('_web2print_verified', $data['verified'] ?? false ? 'yes' : 'no');
                    
                    // Log detalhado do salvamento
                    error_log(sprintf(
                        'Web2Print: URL PDF salvo no pedido #%d: %s (Acessível: %s, Hash: %s)',
                        $order->get_id(),
                        $pdf_url,
                        $is_accessible ? 'SIM' : 'NÃO',
                        substr($data['content_hash'] ?? '', 0, 8)
                    ));
                    
                } else {
                    // URL inválido - log de erro
                    error_log(sprintf(
                        'Web2Print: URL inválido no pedido #%d: %s',
                        $order->get_id(),
                        $pdf_url
                    ));
                    
                    // Salvar URL mesmo sendo inválido para debugging
                    $item->add_meta_data('_web2print_pdf_url', $pdf_url);
                    $item->add_meta_data('_web2print_pdf_url_verified', 'invalid');
                }
            }
            
            // Salvar dados legíveis para o admin (com escape)
            $item->add_meta_data(__('Papel', 'web2print-integration'), esc_html($data['calculation']['breakdown']['paper_info']));
            $item->add_meta_data(__('Encadernação', 'web2print-integration'), esc_html($data['calculation']['breakdown']['binding_info']));
            
            if (!empty($data['calculation']['breakdown']['finishing_info'])) {
                $item->add_meta_data(__('Acabamentos', 'web2print-integration'), esc_html($data['calculation']['breakdown']['finishing_info']));
            }
            
            $item->add_meta_data(__('Páginas', 'web2print-integration'), sprintf(
                '%d coloridas + %d P&B = %d total',
                $data['calculation']['breakdown']['color_pages'],
                $data['calculation']['breakdown']['mono_pages'],
                $data['calculation']['breakdown']['total_pages']
            ));
            
            $item->add_meta_data(__('Cópias', 'web2print-integration'), $data['config']['copy_quantity']);
            $item->add_meta_data(__('Custo por Cópia', 'web2print-integration'), 'R$ ' . number_format($data['calculation']['cost_details']['cost_per_copy'], 2, ',', '.'));
            
            // CRÍTICO: Link do arquivo para download da gráfica (com validação)
            if (isset($data['pdf_file_url']) && !empty($data['pdf_file_url'])) {
                $file_link = sprintf(
                    '<a href="%s" target="_blank" rel="noopener">📥 %s (%s)</a>',
                    esc_url($data['pdf_file_url']),
                    esc_html($data['pdf_filename'] ?? 'arquivo.pdf'),
                    size_format($data['pdf_filesize'] ?? 0)
                );
                $item->add_meta_data(__('📁 Arquivo para Impressão', 'web2print-integration'), $file_link, true);
                
                // URL formatado para fácil acesso da gráfica
                $item->add_meta_data(__('🔗 URL do Arquivo', 'web2print-integration'), esc_url($data['pdf_file_url']), true);
            }
            
            // 5. HOOK DE INTEGRAÇÃO PARA SISTEMAS EXTERNOS
            $pdf_data = array(
                'order_id' => $order->get_id(),
                'item_id' => $item->get_id(),
                'pdf_url' => $data['pdf_file_url'] ?? '',
                'pdf_filename' => $data['pdf_filename'] ?? '',
                'pdf_hash' => $data['content_hash'] ?? '',
                'verification_token' => $data['verification_token'] ?? '',
                'analysis_method' => $data['analysis_method'] ?? '',
                'is_verified' => $data['verified'] ?? false
            );
            
            // Disparar ação para integrações externas (gráficas, ERP, etc.)
            do_action('web2print_order_item_saved', $pdf_data, $data);
            
            // Log final de sucesso
            error_log(sprintf(
                'Web2Print: Metadados salvos com sucesso no pedido #%d, item #%d. Hook disparado.',
                $order->get_id(),
                $item->get_id()
            ));
        }
    }
    
    public function admin_menu() {
        add_options_page(
            __('Configurações Web2Print', 'web2print-integration'),
            __('Web2Print', 'web2print-integration'),
            'manage_options',
            'web2print-settings',
            array($this, 'admin_page')
        );
        
        // Página de monitoramento
        add_management_page(
            __('Monitoramento Web2Print API', 'web2print-integration'),
            __('Web2Print Monitor', 'web2print-integration'),
            'manage_options',
            'web2print-monitor',
            array($this, 'monitor_dashboard_page')
        );
    }
    
    public function admin_page() {
        if (isset($_POST['submit'])) {
            // Verificar nonce CSRF
            if (!wp_verify_nonce($_POST['web2print_nonce'], 'web2print_settings')) {
                wp_die(__('Falha na verificação de segurança', 'web2print-integration'));
            }
            
            // Verificar permissões
            if (!current_user_can('manage_options')) {
                wp_die(__('Permissão insuficiente', 'web2print-integration'));
            }
            
            // Configurações da API
            update_option('web2print_api_endpoint', sanitize_url($_POST['api_endpoint']));
            
            // Só atualizar API key se não for o placeholder de asteriscos
            $new_api_key = sanitize_text_field($_POST['api_key']);
            if (!empty($new_api_key) && $new_api_key !== str_repeat('*', 20)) {
                update_option('web2print_api_key', $new_api_key);
            }
            
            // Configurações de monitoramento
            update_option('web2print_alert_email', sanitize_email($_POST['alert_email']));
            update_option('web2print_slow_threshold', intval($_POST['slow_threshold']));
            update_option('web2print_check_interval', intval($_POST['check_interval']));
            update_option('web2print_email_alerts', isset($_POST['email_alerts']) ? 1 : 0);
            update_option('web2print_monitoring_enabled', isset($_POST['monitoring_enabled']) ? 1 : 0);
            
            echo '<div class="notice notice-success"><p>' . __('Configurações salvas!', 'web2print-integration') . '</p></div>';
        }
        
        $api_endpoint = get_option('web2print_api_endpoint', '');
        $api_key = get_option('web2print_api_key', '');
        
        // Configurações de monitoramento
        $alert_email = get_option('web2print_alert_email', get_option('admin_email'));
        $slow_threshold = get_option('web2print_slow_threshold', 5000);
        $check_interval = get_option('web2print_check_interval', 5);
        $email_alerts = get_option('web2print_email_alerts', true);
        $monitoring_enabled = get_option('web2print_monitoring_enabled', true);
        
        // Status atual da API
        $api_status = get_transient('web2print_api_status');
        $last_check = get_transient('web2print_last_check');
        ?>
        <div class="wrap">
            <h1><?php _e('Configurações Web2Print', 'web2print-integration'); ?></h1>
            
            <?php if ($api_status): ?>
            <div class="web2print-status-summary" style="margin: 20px 0; padding: 15px; border-left: 4px solid <?php echo $api_status === 'healthy' ? '#46b450' : ($api_status === 'slow' ? '#ffb900' : '#dc3232'); ?>; background: <?php echo $api_status === 'healthy' ? '#f7fcf0' : ($api_status === 'slow' ? '#fffbf0' : '#fef7f7'); ?>;">
                <h3><?php _e('Status da API:', 'web2print-integration'); ?> <?php echo $this->get_status_display($api_status); ?></h3>
                <?php if ($last_check): ?>
                    <p><?php _e('Última verificação:', 'web2print-integration'); ?> <?php echo $last_check; ?></p>
                <?php endif; ?>
                <p><a href="<?php echo admin_url('tools.php?page=web2print-monitor'); ?>" class="button button-secondary">🔍 <?php _e('Ver Dashboard Completo', 'web2print-integration'); ?></a></p>
            </div>
            <?php endif; ?>
            
            <form method="post" action="">
                <?php wp_nonce_field('web2print_settings', 'web2print_nonce'); ?>
                
                <h2><?php _e('🔗 Conexão com API', 'web2print-integration'); ?></h2>
                <table class="form-table">
                    <tr>
                        <th scope="row"><?php _e('Endpoint da API', 'web2print-integration'); ?></th>
                        <td>
                            <input type="url" name="api_endpoint" value="<?php echo esc_attr($api_endpoint); ?>" class="regular-text" required />
                            <p class="description"><?php _e('Ex: https://seu-app.replit.app/api/v1/calculate_final', 'web2print-integration'); ?></p>
                        </td>
                    </tr>
                    <tr>
                        <th scope="row"><?php _e('Chave da API', 'web2print-integration'); ?></th>
                        <td>
                            <input type="password" name="api_key" value="<?php echo esc_attr($api_key ? str_repeat('*', 20) : ''); ?>" class="regular-text" autocomplete="new-password" />
                            <p class="description"><?php _e('Chave de acesso para autenticação na API', 'web2print-integration'); ?></p>
                            <?php if ($api_key): ?>
                                <p><small><?php _e('Chave configurada. Digite uma nova para alterar.', 'web2print-integration'); ?></small></p>
                            <?php endif; ?>
                        </td>
                    </tr>
                </table>
                
                <h2><?php _e('🔍 Monitoramento da API', 'web2print-integration'); ?></h2>
                <table class="form-table">
                    <tr>
                        <th scope="row"><?php _e('Ativar Monitoramento', 'web2print-integration'); ?></th>
                        <td>
                            <label>
                                <input type="checkbox" name="monitoring_enabled" value="1" <?php checked($monitoring_enabled); ?> />
                                <?php _e('Monitorar automaticamente a saúde da API', 'web2print-integration'); ?>
                            </label>
                            <p class="description"><?php _e('Quando ativo, verifica a API automaticamente e envia alertas em caso de problemas.', 'web2print-integration'); ?></p>
                        </td>
                    </tr>
                    <tr>
                        <th scope="row"><?php _e('Intervalo de Verificação', 'web2print-integration'); ?></th>
                        <td>
                            <select name="check_interval">
                                <option value="2" <?php selected($check_interval, 2); ?>><?php _e('2 minutos', 'web2print-integration'); ?></option>
                                <option value="5" <?php selected($check_interval, 5); ?>><?php _e('5 minutos', 'web2print-integration'); ?></option>
                                <option value="10" <?php selected($check_interval, 10); ?>><?php _e('10 minutos', 'web2print-integration'); ?></option>
                                <option value="15" <?php selected($check_interval, 15); ?>><?php _e('15 minutos', 'web2print-integration'); ?></option>
                            </select>
                            <p class="description"><?php _e('Com que frequência verificar a saúde da API.', 'web2print-integration'); ?></p>
                        </td>
                    </tr>
                    <tr>
                        <th scope="row"><?php _e('Limite de Lentidão', 'web2print-integration'); ?></th>
                        <td>
                            <input type="number" name="slow_threshold" value="<?php echo esc_attr($slow_threshold); ?>" min="1000" max="30000" step="500" /> ms
                            <p class="description"><?php _e('Tempo de resposta acima do qual a API é considerada lenta.', 'web2print-integration'); ?></p>
                        </td>
                    </tr>
                </table>
                
                <h2><?php _e('📧 Alertas por Email', 'web2print-integration'); ?></h2>
                <table class="form-table">
                    <tr>
                        <th scope="row"><?php _e('Ativar Alertas por Email', 'web2print-integration'); ?></th>
                        <td>
                            <label>
                                <input type="checkbox" name="email_alerts" value="1" <?php checked($email_alerts); ?> />
                                <?php _e('Enviar alertas por email quando houver problemas', 'web2print-integration'); ?>
                            </label>
                        </td>
                    </tr>
                    <tr>
                        <th scope="row"><?php _e('Email para Alertas', 'web2print-integration'); ?></th>
                        <td>
                            <input type="email" name="alert_email" value="<?php echo esc_attr($alert_email); ?>" class="regular-text" />
                            <p class="description"><?php _e('Email que receberá os alertas de problemas com a API.', 'web2print-integration'); ?></p>
                        </td>
                    </tr>
                    <tr>
                        <th scope="row"><?php _e('Teste de Alerta', 'web2print-integration'); ?></th>
                        <td>
                            <button type="button" onclick="sendTestAlert()" class="button button-secondary">
                                📧 <?php _e('Enviar Email de Teste', 'web2print-integration'); ?>
                            </button>
                            <p class="description"><?php _e('Envie um email de teste para verificar se os alertas estão funcionando.', 'web2print-integration'); ?></p>
                        </td>
                    </tr>
                </table>
                
                <?php submit_button(__('Salvar Configurações', 'web2print-integration')); ?>
            </form>
            
            <script>
            function sendTestAlert() {
                const button = event.target;
                button.disabled = true;
                button.textContent = '<?php _e('Enviando...', 'web2print-integration'); ?>';
                
                fetch(ajaxurl, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                    },
                    body: 'action=web2print_send_test_alert&nonce=<?php echo wp_create_nonce('web2print_test_alert'); ?>'
                })
                .then(response => response.json())
                .then(data => {
                    alert(data.data.message || '<?php _e('Email enviado!', 'web2print-integration'); ?>');
                })
                .catch(error => {
                    alert('<?php _e('Erro ao enviar:', 'web2print-integration'); ?> ' + error);
                })
                .finally(() => {
                    button.disabled = false;
                    button.textContent = '📧 <?php _e('Enviar Email de Teste', 'web2print-integration'); ?>';
                });
            }
            </script>
        </div>
        <?php
    }
    
    /**
     * Enqueue CSS e JS para área administrativa
     */
    public function admin_enqueue_scripts($hook) {
        // Verificar se estamos na tela de pedidos do WooCommerce
        if ($hook === 'post.php' || $hook === 'edit.php') {
            global $post_type;
            if ($post_type === 'shop_order') {
                wp_enqueue_style(
                    'web2print-admin-styles',
                    WEB2PRINT_PLUGIN_URL . 'css/web2print-admin.css',
                    array(),
                    WEB2PRINT_VERSION
                );
            }
        }
    }
    
    /**
     * Display destacado dos dados Web2Print no painel administrativo
     */
    public function display_web2print_order_details($product, $item, $item_id) {
        // Verificar se este item tem dados Web2Print
        $config = $item->get_meta('_web2print_config');
        $calculation = $item->get_meta('_web2print_calculation');
        $pdf_url = $item->get_meta('_web2print_pdf_url');
        $pdf_filename = $item->get_meta('_web2print_pdf_filename');
        $pdf_filesize = $item->get_meta('_web2print_pdf_filesize');
        $pdf_verified = $item->get_meta('_web2print_pdf_url_verified');
        
        if (!$config || !$calculation || !$pdf_url) {
            return; // Não é um item Web2Print
        }
        
        // Preparar dados para exibição
        $breakdown = $calculation['breakdown'] ?? array();
        $total_pages = $breakdown['total_pages'] ?? 0;
        $color_pages = $breakdown['color_pages'] ?? 0;
        $mono_pages = $breakdown['mono_pages'] ?? 0;
        $paper_info = $breakdown['paper_info'] ?? '';
        $binding_info = $breakdown['binding_info'] ?? '';
        $finishing_info = $breakdown['finishing_info'] ?? '';
        $copy_quantity = $config['copy_quantity'] ?? 1;
        
        // Preparar link de download seguro
        $download_nonce = wp_create_nonce('web2print_download_' . $item_id);
        $download_url = add_query_arg(array(
            'action' => 'web2print_download_pdf',
            'item_id' => $item_id,
            'nonce' => $download_nonce
        ), admin_url('admin-ajax.php'));
        
        // Formatar tamanho do arquivo
        $file_size_formatted = '';
        if ($pdf_filesize) {
            $file_size_formatted = ' (' . size_format($pdf_filesize) . ')';
        }
        
        // Status de verificação
        $verified_status = ($pdf_verified === 'yes') ? 
            '<span class="web2print-verified">✅ Verificado</span>' : 
            '<span class="web2print-unverified">⚠️ Não verificado</span>';
        
        ?>
        <div class="web2print-production-info">
            <h4>📄 DADOS PARA PRODUÇÃO</h4>
            
            <div class="web2print-download-section">
                <strong>🔗 Download PDF:</strong>
                <a href="<?php echo esc_url($download_url); ?>" 
                   class="web2print-download-link" 
                   target="_blank">
                    📥 <?php echo esc_html($pdf_filename); ?><?php echo esc_html($file_size_formatted); ?>
                </a>
                <?php echo $verified_status; ?>
            </div>
            
            <div class="web2print-analysis-section">
                <h5>📊 ANÁLISE DO ARQUIVO:</h5>
                <ul class="web2print-page-info">
                    <li><strong>Páginas Totais:</strong> <?php echo intval($total_pages); ?></li>
                    <li><strong>Páginas a Cores:</strong> <?php echo intval($color_pages); ?></li>
                    <li><strong>Páginas Preto & Branco:</strong> <?php echo intval($mono_pages); ?></li>
                </ul>
            </div>
            
            <div class="web2print-specs-section">
                <h5>⚙️ ESPECIFICAÇÕES:</h5>
                <ul class="web2print-specs-list">
                    <?php if ($paper_info): ?>
                        <li><strong>Papel:</strong> <?php echo esc_html($paper_info); ?></li>
                    <?php endif; ?>
                    
                    <?php if ($binding_info): ?>
                        <li><strong>Acabamento:</strong> <?php echo esc_html($binding_info); ?></li>
                    <?php endif; ?>
                    
                    <?php if ($finishing_info): ?>
                        <li><strong>Acabamentos Extras:</strong> <?php echo esc_html($finishing_info); ?></li>
                    <?php endif; ?>
                    
                    <li><strong>Cópias:</strong> <?php echo intval($copy_quantity); ?></li>
                </ul>
            </div>
        </div>
        <?php
    }
    
    // ============================================
    // SISTEMA DE MONITORAMENTO DA API
    // ============================================
    
    /**
     * Agendar monitoramento automático da API
     */
    public function schedule_api_monitoring() {
        $interval = get_option('web2print_check_interval', 5) * 60; // converter para segundos
        
        if (!wp_next_scheduled('web2print_monitor_api')) {
            wp_schedule_event(time(), 'five_minutes', 'web2print_monitor_api');
        }
        
        // Registrar intervalo personalizado se necessário
        if (!wp_get_schedule('web2print_monitor_api')) {
            add_filter('cron_schedules', function($schedules) use ($interval) {
                $schedules['web2print_interval'] = array(
                    'interval' => $interval,
                    'display' => sprintf(__('A cada %d minutos', 'web2print-integration'), $interval / 60)
                );
                return $schedules;
            });
        }
    }
    
    /**
     * Monitorar saúde da API automaticamente - FASE 1 OTIMIZADA
     */
    public function monitor_api_health() {
        if (empty($this->api_endpoint) || empty($this->api_key)) {
            return; // Não monitorar se não configurado
        }
        
        $start_time = microtime(true);
        $health_url = rtrim($this->api_endpoint, '/') . '/health';
        
        // FASE 1: Timeout otimizado para 3 segundos (alinhado com Flask)
        $response = wp_remote_get($health_url, array(
            'timeout' => 3, // Otimizado da Fase 1
            'headers' => array(
                'X-API-Key' => $this->api_key
            ),
            'user-agent' => 'Web2Print-Monitor/1.0'
        ));
        
        $response_time = (microtime(true) - $start_time) * 1000; // ms
        $current_status = get_transient('web2print_api_status');
        $slow_threshold = get_option('web2print_slow_threshold', 5000);
        
        // Salvar métricas
        $this->save_api_metrics($response_time, $response);
        
        if (is_wp_error($response)) {
            $this->handle_api_down($response->get_error_message(), $current_status);
            return;
        }
        
        $code = wp_remote_retrieve_response_code($response);
        
        if ($code !== 200) {
            $this->handle_api_down("HTTP {$code}", $current_status);
            return;
        }
        
        if ($response_time > $slow_threshold) {
            $this->handle_api_slow($response_time, $current_status);
            return;
        }
        
        $this->handle_api_healthy($response_time, $current_status);
    }
    
    /**
     * Tratar API indisponível
     */
    private function handle_api_down($error_message, $previous_status) {
        set_transient('web2print_api_status', 'down', 300); // 5 minutos
        set_transient('web2print_api_error', $error_message, 300);
        set_transient('web2print_last_check', current_time('mysql'), 300);
        
        // Enviar alerta apenas se mudou de status
        if ($previous_status !== 'down') {
            $this->send_api_alert('down', "API indisponível: {$error_message}");
        }
        
        // Log para debugging
        error_log("[Web2Print Monitor] API DOWN: {$error_message}");
    }
    
    /**
     * Tratar API lenta
     */
    private function handle_api_slow($response_time, $previous_status) {
        set_transient('web2print_api_status', 'slow', 300);
        set_transient('web2print_api_response_time', $response_time, 300);
        set_transient('web2print_last_check', current_time('mysql'), 300);
        
        // Enviar alerta apenas se mudou de status ou primeira detecção
        if ($previous_status !== 'slow') {
            $this->send_api_alert('slow', "API lenta: {$response_time}ms");
        }
        
        error_log("[Web2Print Monitor] API SLOW: {$response_time}ms");
    }
    
    /**
     * Tratar API saudável
     */
    private function handle_api_healthy($response_time, $previous_status) {
        set_transient('web2print_api_status', 'healthy', 300);
        set_transient('web2print_api_response_time', $response_time, 300);
        set_transient('web2print_last_check', current_time('mysql'), 300);
        
        // Enviar alerta de recuperação se estava com problema
        if ($previous_status === 'down' || $previous_status === 'slow') {
            $this->send_api_alert('recovered', "API recuperada: {$response_time}ms");
        }
    }
    
    /**
     * Salvar métricas da API para histórico
     */
    private function save_api_metrics($response_time, $response) {
        $metrics = get_option('web2print_api_metrics', array());
        $timestamp = current_time('timestamp');
        
        // Manter apenas últimas 24 horas
        $day_ago = $timestamp - (24 * 60 * 60);
        $metrics = array_filter($metrics, function($metric) use ($day_ago) {
            return $metric['timestamp'] > $day_ago;
        });
        
        // Adicionar nova métrica
        $metrics[] = array(
            'timestamp' => $timestamp,
            'response_time' => $response_time,
            'status' => is_wp_error($response) ? 'error' : wp_remote_retrieve_response_code($response),
            'success' => !is_wp_error($response) && wp_remote_retrieve_response_code($response) === 200
        );
        
        update_option('web2print_api_metrics', $metrics);
    }
    
    /**
     * Enviar alertas por email
     */
    private function send_api_alert($status, $details = '') {
        if (!get_option('web2print_email_alerts', true)) {
            return; // Alertas desabilitados
        }
        
        $admin_email = get_option('web2print_alert_email', get_option('admin_email'));
        $site_name = get_bloginfo('name');
        
        $status_messages = array(
            'down' => '🚨 ALERTA CRÍTICO',
            'slow' => '⚠️ ALERTA DE PERFORMANCE',
            'recovered' => '✅ API RECUPERADA'
        );
        
        $subject = sprintf('[%s] %s - Web2Print API', $site_name, $status_messages[$status] ?? 'ALERTA');
        
        $message = sprintf("
        ALERTA DO SISTEMA WEB2PRINT
        ===========================
        
        Site: %s
        Status: %s
        Horário: %s
        Detalhes: %s
        
        AÇÕES RECOMENDADAS:
        • Verificar status do Replit/servidor
        • Checar logs da aplicação Flask
        • Testar endpoint manualmente: %s
        
        Dashboard: %s
        ",
            $site_name,
            $status,
            current_time('Y-m-d H:i:s'),
            $details,
            $this->api_endpoint . '/health',
            admin_url('admin.php?page=web2print-monitor')
        );
        
        wp_mail($admin_email, $subject, $message);
        
        // Log do envio
        error_log("[Web2Print Monitor] Email alert sent: {$status} - {$details}");
    }
    
    /**
     * Exibir notificações de status da API no painel
     */
    public function display_api_status_notices() {
        if (!current_user_can('manage_options')) {
            return;
        }
        
        $api_status = get_transient('web2print_api_status');
        
        if ($api_status === 'down') {
            $error = get_transient('web2print_api_error');
            echo '<div class="notice notice-error">';
            echo '<p><strong>🚨 Web2Print API INDISPONÍVEL!</strong> ';
            echo 'Os produtos de impressão estão temporariamente desabilitados. ';
            echo '<br><strong>Erro:</strong> ' . esc_html($error) . ' ';
            echo '<a href="' . admin_url('admin.php?page=web2print-monitor') . '">Ver Detalhes</a></p>';
            echo '</div>';
        }
        
        if ($api_status === 'slow') {
            $response_time = get_transient('web2print_api_response_time');
            echo '<div class="notice notice-warning">';
            echo '<p><strong>⚠️ Web2Print API LENTA!</strong> ';
            echo 'Tempos de resposta acima do normal (' . round($response_time) . 'ms). ';
            echo 'Monitorando... <a href="' . admin_url('admin.php?page=web2print-monitor') . '">Ver Status</a></p>';
            echo '</div>';
        }
    }
    
    /**
     * Verificar API antes de adicionar ao carrinho (proteção contra R$ 0,00)
     */
    public function check_api_before_add_to_cart($passed, $product_id, $quantity) {
        // Verificar se é produto Web2Print
        $product = wc_get_product($product_id);
        if (!$product || $product->get_meta('_enable_web2print') !== 'yes') {
            return $passed; // Não é produto Web2Print
        }
        
        $api_status = get_transient('web2print_api_status');
        
        if ($api_status === 'down') {
            wc_add_notice('🚨 Serviço de impressão temporariamente indisponível. Tente novamente em alguns minutos.', 'error');
            return false;
        }
        
        if ($api_status === 'slow') {
            wc_add_notice('⚠️ O serviço está mais lento que o normal. O cálculo pode demorar um pouco mais.', 'notice');
        }
        
        return $passed;
    }
    
    /**
     * Download seguro de PDF com verificação de nonce e permissões
     */
    public function secure_pdf_download() {
        // Verificar permissão básica para editar pedidos
        if (!current_user_can('edit_shop_orders')) {
            wp_die(__('Você não tem permissão para acessar este arquivo.', 'web2print-integration'), 403);
        }
        
        $item_id = intval($_GET['item_id'] ?? 0);
        $nonce = sanitize_text_field($_GET['nonce'] ?? '');
        
        // Validar item_id
        if (!$item_id || $item_id <= 0) {
            wp_die(__('ID do item inválido.', 'web2print-integration'), 400);
        }
        
        // Verificar nonce específico para este item
        if (!wp_verify_nonce($nonce, 'web2print_download_' . $item_id)) {
            wp_die(__('Link de download inválido ou expirado.', 'web2print-integration'), 403);
        }
        
        // Buscar item do pedido usando função segura do WooCommerce
        $order_item = WC_Order_Factory::get_order_item($item_id);
        if (!$order_item || !is_a($order_item, 'WC_Order_Item_Product')) {
            wp_die(__('Item do pedido não encontrado.', 'web2print-integration'), 404);
        }
        
        // Verificar se usuário tem acesso ao pedido específico
        $order_id = $order_item->get_order_id();
        $order = wc_get_order($order_id);
        if (!$order) {
            wp_die(__('Pedido não encontrado.', 'web2print-integration'), 404);
        }
        
        // Verificar permissão específica para este pedido
        if (!current_user_can('edit_shop_order', $order_id)) {
            wp_die(__('Você não tem permissão para acessar este pedido.', 'web2print-integration'), 403);
        }
        
        // Extrair dados do PDF
        $pdf_url = $order_item->get_meta('_web2print_pdf_url');
        $pdf_filename = $order_item->get_meta('_web2print_pdf_filename');
        $pdf_local_path = $order_item->get_meta('_web2print_pdf_local_path');
        
        if (!$pdf_url && !$pdf_local_path) {
            wp_die(__('Arquivo PDF não encontrado.', 'web2print-integration'), 404);
        }
        
        // SEGURANÇA: Validação rigorosa do diretório de uploads
        $upload_dir = wp_upload_dir();
        $uploads_base = realpath($upload_dir['basedir']);
        $uploads_url = $upload_dir['baseurl'];
        
        if (!$uploads_base) {
            error_log('Web2Print Security: Diretório de uploads não encontrado');
            wp_die(__('Erro interno do servidor.', 'web2print-integration'), 500);
        }
        
        // PRIORIDADE: Servir arquivo local (mais seguro)
        if ($pdf_local_path) {
            // Validação rigorosa do caminho local
            $real_path = realpath($pdf_local_path);
            
            // Verificar se arquivo existe e está dentro dos uploads
            if (!$real_path || !file_exists($real_path) || !is_readable($real_path)) {
                wp_die(__('Arquivo não encontrado no servidor.', 'web2print-integration'), 404);
            }
            
            // CRÍTICO: Verificar se arquivo está dentro do diretório de uploads
            if (strpos($real_path, $uploads_base . DIRECTORY_SEPARATOR) !== 0) {
                error_log(sprintf('Web2Print Security: Tentativa de acesso fora de uploads. Path: %s, Uploads: %s', $real_path, $uploads_base));
                wp_die(__('Acesso ao arquivo não permitido.', 'web2print-integration'), 403);
            }
            
            // Verificar se é realmente um PDF
            $file_type = mime_content_type($real_path);
            if ($file_type !== 'application/pdf') {
                error_log(sprintf('Web2Print Security: Arquivo não é PDF. Type: %s', $file_type));
                wp_die(__('Tipo de arquivo não permitido.', 'web2print-integration'), 403);
            }
            
            // Desativar output buffering para download limpo
            if (ob_get_level()) {
                ob_end_clean();
            }
            
            // Headers seguros para download
            header('Content-Type: application/pdf');
            header('Content-Disposition: attachment; filename="' . sanitize_file_name($pdf_filename) . '"');
            header('Content-Length: ' . filesize($real_path));
            header('X-Content-Type-Options: nosniff');
            header('Cache-Control: private, no-cache, no-store, must-revalidate');
            header('Pragma: no-cache');
            header('Expires: 0');
            
            // Log completo para auditoria
            error_log(sprintf(
                'Web2Print: Download LOCAL - Order: %d, Item: %d, User: %d (%s), IP: %s, File: %s',
                $order_id,
                $item_id,
                get_current_user_id(),
                wp_get_current_user()->user_login,
                $_SERVER['REMOTE_ADDR'] ?? 'unknown',
                basename($real_path)
            ));
            
            readfile($real_path);
            exit;
        }
        
        // FALLBACK: URL validada (apenas se local não disponível)
        if ($pdf_url) {
            // Verificar se URL é válida
            if (!filter_var($pdf_url, FILTER_VALIDATE_URL)) {
                wp_die(__('URL do arquivo inválida.', 'web2print-integration'), 400);
            }
            
            // CRÍTICO: Verificar se URL pertence ao domínio de uploads
            $parsed_url = parse_url($pdf_url);
            $parsed_uploads = parse_url($uploads_url);
            
            // Validar estrutura das URLs
            if (!$parsed_url || !$parsed_uploads || 
                !isset($parsed_url['host']) || !isset($parsed_uploads['host']) ||
                !isset($parsed_url['path']) || !isset($parsed_uploads['path'])) {
                error_log(sprintf('Web2Print Security: URL malformada. URL: %s', $pdf_url));
                wp_die(__('URL do arquivo inválida.', 'web2print-integration'), 400);
            }
            
            // Verificar mesmo host e path prefix
            if ($parsed_url['host'] !== $parsed_uploads['host'] || 
                strpos($parsed_url['path'], $parsed_uploads['path']) !== 0) {
                error_log(sprintf('Web2Print Security: URL fora dos uploads. URL host: %s, Uploads host: %s', 
                    $parsed_url['host'], $parsed_uploads['host']));
                wp_die(__('Acesso ao arquivo não permitido.', 'web2print-integration'), 403);
            }
            
            // Log completo para auditoria
            error_log(sprintf(
                'Web2Print: Download URL - Order: %d, Item: %d, User: %d (%s), IP: %s, URL: %s',
                $order_id,
                $item_id,
                get_current_user_id(),
                wp_get_current_user()->user_login,
                $_SERVER['REMOTE_ADDR'] ?? 'unknown',
                $pdf_url
            ));
            
            // Redirect seguro para URL validada
            wp_redirect($pdf_url);
            exit;
        }
        
        wp_die(__('Nenhum arquivo disponível para download.', 'web2print-integration'), 404);
    }
    
    /**
     * Página de dashboard de monitoramento
     */
    public function monitor_dashboard_page() {
        $api_status = get_transient('web2print_api_status');
        $response_time = get_transient('web2print_api_response_time');
        $last_check = get_transient('web2print_last_check');
        $metrics = get_option('web2print_api_metrics', array());
        
        // Calcular estatísticas das últimas 24h
        $uptime = $this->calculate_uptime($metrics);
        $avg_response_time = $this->calculate_avg_response_time($metrics);
        $failure_count = $this->count_failures($metrics);
        
        ?>
        <div class="wrap">
            <h1>🔍 <?php _e('Monitoramento Web2Print API', 'web2print-integration'); ?></h1>
            
            <div class="web2print-monitor-grid" style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin: 20px 0;">
                <div class="web2print-status-card <?php echo $this->get_status_css_class($api_status); ?>" style="padding: 20px; border: 2px solid; border-radius: 8px;">
                    <h3><?php _e('Status Atual', 'web2print-integration'); ?></h3>
                    <div class="status-indicator" style="font-size: 24px; font-weight: bold;">
                        <?php echo $this->get_status_display($api_status); ?>
                    </div>
                    <?php if ($response_time): ?>
                        <p><?php _e('Tempo de resposta:', 'web2print-integration'); ?> <?php echo round($response_time); ?>ms</p>
                    <?php endif; ?>
                    <p><?php _e('Última verificação:', 'web2print-integration'); ?> <?php echo $last_check ? $last_check : __('Nunca', 'web2print-integration'); ?></p>
                </div>
                
                <div class="web2print-metrics-card" style="padding: 20px; border: 1px solid #ddd; border-radius: 8px;">
                    <h3><?php _e('Métricas (24h)', 'web2print-integration'); ?></h3>
                    <ul style="list-style: none; padding: 0;">
                        <li><strong><?php _e('Uptime:', 'web2print-integration'); ?></strong> <?php echo $uptime; ?>%</li>
                        <li><strong><?php _e('Tempo médio:', 'web2print-integration'); ?></strong> <?php echo $avg_response_time; ?>ms</li>
                        <li><strong><?php _e('Falhas:', 'web2print-integration'); ?></strong> <?php echo $failure_count; ?></li>
                        <li><strong><?php _e('Total de checks:', 'web2print-integration'); ?></strong> <?php echo count($metrics); ?></li>
                    </ul>
                </div>
            </div>
            
            <div class="web2print-actions" style="margin: 20px 0;">
                <button onclick="testApiNow()" class="button button-primary">
                    🔄 <?php _e('Testar API Agora', 'web2print-integration'); ?>
                </button>
                <a href="<?php echo admin_url('admin.php?page=web2print-settings'); ?>" class="button">
                    ⚙️ <?php _e('Configurações', 'web2print-integration'); ?>
                </a>
            </div>
            
            <?php if (!empty($metrics)): ?>
            <div class="web2print-history" style="margin: 20px 0;">
                <h3><?php _e('Últimas Verificações', 'web2print-integration'); ?></h3>
                <table class="wp-list-table widefat fixed striped">
                    <thead>
                        <tr>
                            <th><?php _e('Horário', 'web2print-integration'); ?></th>
                            <th><?php _e('Status', 'web2print-integration'); ?></th>
                            <th><?php _e('Tempo de Resposta', 'web2print-integration'); ?></th>
                            <th><?php _e('Sucesso', 'web2print-integration'); ?></th>
                        </tr>
                    </thead>
                    <tbody>
                        <?php foreach (array_slice(array_reverse($metrics), 0, 20) as $metric): ?>
                        <tr>
                            <td><?php echo date('Y-m-d H:i:s', $metric['timestamp']); ?></td>
                            <td><?php echo $metric['status']; ?></td>
                            <td><?php echo round($metric['response_time']); ?>ms</td>
                            <td><?php echo $metric['success'] ? '✅' : '❌'; ?></td>
                        </tr>
                        <?php endforeach; ?>
                    </tbody>
                </table>
            </div>
            <?php endif; ?>
        </div>
        
        <script>
        function testApiNow() {
            const button = event.target;
            button.disabled = true;
            button.textContent = '<?php _e('Testando...', 'web2print-integration'); ?>';
            
            fetch(ajaxurl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: 'action=web2print_test_api_now&nonce=<?php echo wp_create_nonce('web2print_test_api'); ?>'
            })
            .then(response => response.json())
            .then(data => {
                alert(data.message || '<?php _e('Teste concluído!', 'web2print-integration'); ?>');
                location.reload();
            })
            .catch(error => {
                alert('<?php _e('Erro no teste:', 'web2print-integration'); ?> ' + error);
            })
            .finally(() => {
                button.disabled = false;
                button.textContent = '🔄 <?php _e('Testar API Agora', 'web2print-integration'); ?>';
            });
        }
        </script>
        
        <style>
        .web2print-status-card.status-healthy {
            border-color: #46b450;
            background-color: #f7fcf0;
        }
        .web2print-status-card.status-slow {
            border-color: #ffb900;
            background-color: #fffbf0;
        }
        .web2print-status-card.status-down {
            border-color: #dc3232;
            background-color: #fef7f7;
        }
        </style>
        <?php
    }
    
    /**
     * Obter classe CSS para status
     */
    private function get_status_css_class($status) {
        $classes = array(
            'healthy' => 'status-healthy',
            'slow' => 'status-slow',
            'down' => 'status-down'
        );
        return $classes[$status] ?? 'status-unknown';
    }
    
    /**
     * Obter exibição do status
     */
    private function get_status_display($status) {
        $displays = array(
            'healthy' => '✅ ' . __('Saudável', 'web2print-integration'),
            'slow' => '⚠️ ' . __('Lento', 'web2print-integration'),
            'down' => '❌ ' . __('Indisponível', 'web2print-integration')
        );
        return $displays[$status] ?? '❔ ' . __('Desconhecido', 'web2print-integration');
    }
    
    /**
     * Calcular uptime das últimas 24h
     */
    private function calculate_uptime($metrics) {
        if (empty($metrics)) return 0;
        
        $successful = array_filter($metrics, function($metric) {
            return $metric['success'];
        });
        
        return round((count($successful) / count($metrics)) * 100, 1);
    }
    
    /**
     * Calcular tempo médio de resposta
     */
    private function calculate_avg_response_time($metrics) {
        if (empty($metrics)) return 0;
        
        $successful = array_filter($metrics, function($metric) {
            return $metric['success'];
        });
        
        if (empty($successful)) return 0;
        
        $total_time = array_sum(array_column($successful, 'response_time'));
        return round($total_time / count($successful));
    }
    
    /**
     * Contar falhas das últimas 24h
     */
    private function count_failures($metrics) {
        if (empty($metrics)) return 0;
        
        return count(array_filter($metrics, function($metric) {
            return !$metric['success'];
        }));
    }
    
    /**
     * AJAX: Testar API manualmente
     */
    public function ajax_test_api_now() {
        // Verificar nonce
        if (!wp_verify_nonce($_POST['nonce'] ?? '', 'web2print_test_api')) {
            wp_die(__('Acesso negado.', 'web2print-integration'), 403);
        }
        
        if (!current_user_can('manage_options')) {
            wp_die(__('Permissão insuficiente.', 'web2print-integration'), 403);
        }
        
        // Forçar execução do monitoramento
        $this->monitor_api_health();
        
        $status = get_transient('web2print_api_status');
        $response_time = get_transient('web2print_api_response_time');
        
        wp_send_json_success(array(
            'message' => sprintf(
                __('Teste concluído! Status: %s (%sms)', 'web2print-integration'),
                $status ?: 'desconhecido',
                $response_time ? round($response_time) : '?'
            ),
            'status' => $status,
            'response_time' => $response_time
        ));
    }
    
    /**
     * AJAX: Limpar métricas
     */
    public function ajax_clear_metrics() {
        if (!wp_verify_nonce($_POST['nonce'] ?? '', 'web2print_clear_metrics')) {
            wp_die(__('Acesso negado.', 'web2print-integration'), 403);
        }
        
        if (!current_user_can('manage_options')) {
            wp_die(__('Permissão insuficiente.', 'web2print-integration'), 403);
        }
        
        delete_option('web2print_api_metrics');
        delete_transient('web2print_api_status');
        delete_transient('web2print_api_response_time');
        delete_transient('web2print_last_check');
        
        wp_send_json_success(array(
            'message' => __('Histórico limpo com sucesso!', 'web2print-integration')
        ));
    }
    
    /**
     * AJAX: Enviar alerta de teste
     */
    public function ajax_send_test_alert() {
        if (!wp_verify_nonce($_POST['nonce'] ?? '', 'web2print_test_alert')) {
            wp_die(__('Acesso negado.', 'web2print-integration'), 403);
        }
        
        if (!current_user_can('manage_options')) {
            wp_die(__('Permissão insuficiente.', 'web2print-integration'), 403);
        }
        
        $this->send_api_alert('test', 'Este é um alerta de teste enviado pelo administrador.');
        
        wp_send_json_success(array(
            'message' => __('Alerta de teste enviado!', 'web2print-integration')
        ));
    }
}

// Inicializar plugin
new Web2PrintIntegration();

// Hook de ativação
register_activation_hook(__FILE__, 'web2print_activate');
function web2print_activate() {
    // Verificar se WooCommerce está ativo
    if (!class_exists('WooCommerce')) {
        deactivate_plugins(plugin_basename(__FILE__));
        wp_die(__('Este plugin requer WooCommerce para funcionar. Por favor, instale e ative o WooCommerce primeiro.', 'web2print-integration'));
    }
    
    flush_rewrite_rules();
}

// Hook de desativação
register_deactivation_hook(__FILE__, 'web2print_deactivate');
function web2print_deactivate() {
    flush_rewrite_rules();
}
?>