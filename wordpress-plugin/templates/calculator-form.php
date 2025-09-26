<?php
/**
 * Template do formulário de cálculo Web2Print
 */

if (!defined('ABSPATH')) {
    exit;
}
?>

<div id="web2print_calculator" class="web2print-calculator">
    <h3><?php _e('🖨️ Calculadora de Impressão Personalizada', 'web2print-integration'); ?></h3>
    
    <!-- Upload de PDF -->
    <div class="upload-section">
        <h4><?php _e('1. Upload do Arquivo PDF', 'web2print-integration'); ?></h4>
        
        <div id="web2print_upload_zone" class="upload-zone">
            <input type="file" id="web2print_pdf_file" accept=".pdf" style="display: none;">
            <div class="upload-content">
                <span class="upload-icon">📁</span>
                <p><?php _e('Clique para selecionar ou arraste seu arquivo PDF aqui', 'web2print-integration'); ?></p>
                <button type="button" onclick="document.getElementById('web2print_pdf_file').click();" class="btn-upload">
                    <?php _e('Selecionar Arquivo', 'web2print-integration'); ?>
                </button>
            </div>
        </div>
        
        <div id="file_info" class="file-info" style="display: none;"></div>
        
        <div class="analysis-loading" style="display: none;">
            <p><?php _e('🔍 Analisando PDF...', 'web2print-integration'); ?></p>
        </div>
        
        <div id="pdf_analysis" class="pdf-analysis" style="display: none;"></div>
    </div>
    
    <!-- Configuração de Impressão -->
    <div class="web2print-config-section disabled">
        <h4><?php _e('2. Configuração de Impressão', 'web2print-integration'); ?></h4>
        
        <!-- Campos ocultos para dados do PDF -->
        <input type="hidden" id="total_pages" value="0">
        <input type="hidden" id="color_pages" value="0">
        <input type="hidden" id="mono_pages" value="0">
        
        <div class="config-row">
            <div class="config-col">
                <label for="paper_type"><?php _e('Tipo de Papel:', 'web2print-integration'); ?></label>
                <select id="paper_type" class="web2print-config">
                    <option value="sulfite"><?php _e('📋 Sulfite', 'web2print-integration'); ?></option>
                    <option value="couche"><?php _e('✨ Couchê', 'web2print-integration'); ?></option>
                    <option value="reciclado"><?php _e('🌱 Reciclado', 'web2print-integration'); ?></option>
                </select>
            </div>
            
            <div class="config-col">
                <label for="paper_weight"><?php _e('Gramatura:', 'web2print-integration'); ?></label>
                <select id="paper_weight" class="web2print-config">
                    <option value="75">75g</option>
                    <option value="90" selected>90g</option>
                    <option value="115">115g</option>
                    <option value="120">120g</option>
                    <option value="150">150g</option>
                </select>
            </div>
        </div>
        
        <div class="config-row">
            <div class="config-col">
                <label for="binding_type"><?php _e('Encadernação:', 'web2print-integration'); ?></label>
                <select id="binding_type" class="web2print-config">
                    <option value="grampo"><?php _e('📎 Grampo (2 grampos)', 'web2print-integration'); ?></option>
                    <option value="spiral"><?php _e('🌀 Espiral plástica', 'web2print-integration'); ?></option>
                    <option value="wire-o"><?php _e('⚙️ Wire-o (espiral metálica)', 'web2print-integration'); ?></option>
                    <option value="capa-dura"><?php _e('📖 Capa dura', 'web2print-integration'); ?></option>
                </select>
            </div>
            
            <div class="config-col">
                <label for="web2print_quantity"><?php _e('Quantidade:', 'web2print-integration'); ?></label>
                <input type="number" id="web2print_quantity" min="1" max="1000" value="1" class="web2print-config">
            </div>
        </div>
        
        <!-- Acabamentos -->
        <div class="config-row">
            <div class="config-col-full">
                <label><?php _e('Acabamentos (opcionais):', 'web2print-integration'); ?></label>
                <div class="finishing-options">
                    <label><input type="checkbox" class="finishing-option web2print-config" value="laminacao"> <?php _e('🔸 Laminação', 'web2print-integration'); ?></label>
                    <label><input type="checkbox" class="finishing-option web2print-config" value="verniz"> <?php _e('✨ Verniz', 'web2print-integration'); ?></label>
                    <label><input type="checkbox" class="finishing-option web2print-config" value="dobra"> <?php _e('📁 Dobra', 'web2print-integration'); ?></label>
                    <label><input type="checkbox" class="finishing-option web2print-config" value="perfuracao"> <?php _e('🕳️ Perfuração', 'web2print-integration'); ?></label>
                </div>
            </div>
        </div>
    </div>
    
    <!-- Resultado do Cálculo -->
    <div id="cost_result" class="cost-result"></div>
    
    <!-- Botão Adicionar ao Carrinho -->
    <div class="add-to-cart-section">
        <button type="button" id="web2print_add_to_cart" class="btn-add-to-cart" disabled>
            <?php _e('🛒 Adicionar ao Carrinho', 'web2print-integration'); ?>
        </button>
    </div>
</div>