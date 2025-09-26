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
    }
    
    public function init() {
        // Carregar texto do domínio
        load_plugin_textdomain('web2print-integration', false, dirname(plugin_basename(__FILE__)) . '/languages/');
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
        
        $args = array(
            'method' => 'POST',
            'timeout' => 30,
            'headers' => array(
                'Content-Type' => 'application/json',
                'X-API-Key' => $this->api_key
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
        // CRÍTICO: Análise centralizada via Flask API com PyMuPDF
        if (empty($this->api_endpoint) || empty($this->api_key)) {
            error_log('Web2Print: API endpoint ou key não configurados para análise');
            return false;
        }
        
        // Preparar URL da rota de análise
        $analyze_url = rtrim($this->api_endpoint, '/') . '/analyze_pdf_url';
        
        $args = array(
            'method' => 'POST',
            'timeout' => 45, // Tempo maior para download + análise
            'headers' => array(
                'Content-Type' => 'application/json',
                'X-API-Key' => $this->api_key
            ),
            'body' => json_encode(array(
                'pdf_url' => $pdf_url
            ))
        );
        
        $response = wp_remote_post($analyze_url, $args);
        
        if (is_wp_error($response)) {
            error_log('Web2Print Flask Analysis Error: ' . $response->get_error_message());
            return false;
        }
        
        $body = wp_remote_retrieve_body($response);
        $data = json_decode($body, true);
        
        if (wp_remote_retrieve_response_code($response) !== 200) {
            error_log('Web2Print Flask Analysis HTTP Error: ' . wp_remote_retrieve_response_code($response));
            error_log('Response body: ' . $body);
            return false;
        }
        
        if (!$data['success']) {
            error_log('Web2Print Flask Analysis API Error: ' . $data['error']);
            return false;
        }
        
        // Retornar dados da análise precisos do Flask
        return $data['data'];
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
            
            update_option('web2print_api_endpoint', sanitize_url($_POST['api_endpoint']));
            
            // Só atualizar API key se não for o placeholder de asteriscos
            $new_api_key = sanitize_text_field($_POST['api_key']);
            if (!empty($new_api_key) && $new_api_key !== str_repeat('*', 20)) {
                update_option('web2print_api_key', $new_api_key);
            }
            echo '<div class="notice notice-success"><p>' . __('Configurações salvas!', 'web2print-integration') . '</p></div>';
        }
        
        $api_endpoint = get_option('web2print_api_endpoint', '');
        $api_key = get_option('web2print_api_key', '');
        ?>
        <div class="wrap">
            <h1><?php _e('Configurações Web2Print', 'web2print-integration'); ?></h1>
            <form method="post" action="">
                <?php wp_nonce_field('web2print_settings', 'web2print_nonce'); ?>
                <table class="form-table">
                    <tr>
                        <th scope="row"><?php _e('Endpoint da API', 'web2print-integration'); ?></th>
                        <td>
                            <input type="url" name="api_endpoint" value="<?php echo esc_attr($api_endpoint); ?>" class="regular-text" />
                            <p class="description"><?php _e('Ex: https://seu-dominio.com/api/v1/calculate_final', 'web2print-integration'); ?></p>
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
                <?php submit_button(); ?>
            </form>
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