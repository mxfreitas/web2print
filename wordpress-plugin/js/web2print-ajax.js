jQuery(document).ready(function($) {
    'use strict';
    
    var Web2PrintCalculator = {
        
        init: function() {
            this.bindEvents();
            this.initFileUpload();
        },
        
        bindEvents: function() {
            // Evento para upload de arquivo
            $(document).on('change', '#web2print_pdf_file', this.handleFileUpload);
            
            // Evento para cálculo quando configuração muda
            $(document).on('change', '.web2print-config', this.calculateCost);
            
            // Evento para adicionar ao carrinho
            $(document).on('click', '#web2print_add_to_cart', this.addToCart);
            
            // Evento para recalcular quando quantidade muda
            $(document).on('change', '#web2print_quantity', this.calculateCost);
        },
        
        initFileUpload: function() {
            // Configurar drag & drop para upload
            var dropZone = $('#web2print_upload_zone');
            
            if (dropZone.length) {
                dropZone.on('dragover', function(e) {
                    e.preventDefault();
                    $(this).addClass('dragover');
                });
                
                dropZone.on('dragleave', function(e) {
                    e.preventDefault();
                    $(this).removeClass('dragover');
                });
                
                dropZone.on('drop', function(e) {
                    e.preventDefault();
                    $(this).removeClass('dragover');
                    
                    var files = e.originalEvent.dataTransfer.files;
                    if (files.length > 0) {
                        $('#web2print_pdf_file')[0].files = files;
                        Web2PrintCalculator.handleFileUpload();
                    }
                });
            }
        },
        
        handleFileUpload: function() {
            var file = $('#web2print_pdf_file')[0].files[0];
            
            if (!file) return;
            
            // VALIDAÇÃO ROBUSTA DE PDF
            var validation_error = Web2PrintCalculator.validatePDFFile(file);
            if (validation_error) {
                Web2PrintCalculator.showError(validation_error);
                return;
            }
            
            // Mostrar informações do arquivo
            $('#file_info').html(
                '<p><strong>Arquivo:</strong> ' + file.name + '</p>' +
                '<p><strong>Tamanho:</strong> ' + Web2PrintCalculator.formatBytes(file.size) + '</p>'
            ).show();
            
            // Upload REAL do arquivo para análise server-side
            Web2PrintCalculator.uploadPDF(file);
        },
        
        validatePDFFile: function(file) {
            // 1. Verificar extensão do arquivo
            if (!file.name.toLowerCase().endsWith('.pdf')) {
                return web2print_ajax.texts.invalid_file;
            }
            
            // 2. Verificar MIME type
            if (file.type !== 'application/pdf') {
                return web2print_ajax.texts.invalid_file;
            }
            
            // 3. Verificar tamanho (máximo 50MB)
            var maxSize = 50 * 1024 * 1024; // 50MB
            if (file.size > maxSize) {
                return web2print_ajax.texts.file_too_large;
            }
            
            // 4. Verificar tamanho mínimo (pelo menos 1KB)
            if (file.size < 1024) {
                return web2print_ajax.texts.invalid_file;
            }
            
            return null; // Arquivo válido
        },
        
        uploadPDF: function(file) {
            $('.analysis-loading').show();
            
            // Preparar FormData para upload
            var formData = new FormData();
            formData.append('action', 'web2print_upload_pdf');
            formData.append('nonce', web2print_ajax.nonce);
            formData.append('pdf_file', file);
            
            $.ajax({
                url: web2print_ajax.ajax_url,
                type: 'POST',
                data: formData,
                processData: false,
                contentType: false,
                success: function(response) {
                    $('.analysis-loading').hide();
                    
                    if (response.success) {
                        var data = response.data;
                        
                        // Salvar dados validados pelo servidor
                        $('#total_pages').val(data.total_pages);
                        $('#color_pages').val(data.color_pages);
                        $('#mono_pages').val(data.mono_pages);
                        
                        // Mostrar resultado da análise
                        $('#pdf_analysis').html(
                            '<div class="analysis-result">' +
                            '<h4>📊 Análise do PDF (Verificada pelo Servidor)</h4>' +
                            '<p><strong>Total de páginas:</strong> ' + data.total_pages + '</p>' +
                            '<p><strong>Páginas coloridas:</strong> ' + data.color_pages + '</p>' +
                            '<p><strong>Páginas monocromáticas:</strong> ' + data.mono_pages + '</p>' +
                            '<p><em>✓ Análise validada e segura</em></p>' +
                            '</div>'
                        ).show();
                        
                        // Habilitar configurações
                        $('.web2print-config-section').removeClass('disabled');
                        
                        // Calcular custo inicial
                        Web2PrintCalculator.calculateCost();
                        
                    } else {
                        Web2PrintCalculator.showError(response.data.message || web2print_ajax.texts.error);
                    }
                },
                error: function(xhr) {
                    $('.analysis-loading').hide();
                    
                    // ERRO HANDLING MELHORADO - mostrar mensagens específicas do servidor
                    var error_msg = web2print_ajax.texts.upload_error;
                    
                    try {
                        if (xhr.responseJSON && xhr.responseJSON.data && xhr.responseJSON.data.message) {
                            error_msg = xhr.responseJSON.data.message;
                        } else if (xhr.responseText) {
                            var response = JSON.parse(xhr.responseText);
                            if (response.data && response.data.message) {
                                error_msg = response.data.message;
                            }
                        }
                    } catch (e) {
                        // Se não conseguir parsear, usar mensagem padrão
                        console.log('Erro ao parsear resposta do servidor:', e);
                    }
                    
                    Web2PrintCalculator.showError(error_msg);
                }
            });
        },
        
        calculateCost: function() {
            var colorPages = parseInt($('#color_pages').val()) || 0;
            var monoPages = parseInt($('#mono_pages').val()) || 0;
            
            if (colorPages === 0 && monoPages === 0) {
                Web2PrintCalculator.showError('Faça upload de um PDF primeiro');
                return;
            }
            
            // Não enviar color_pages/mono_pages - servidor usará dados verificados
            var data = {
                action: 'web2print_calculate',
                nonce: web2print_ajax.nonce,
                paper_type: $('#paper_type').val() || 'sulfite',
                paper_weight: parseInt($('#paper_weight').val()) || 90,
                binding_type: $('#binding_type').val() || 'grampo',
                finishing: Web2PrintCalculator.getSelectedFinishing(),
                copy_quantity: parseInt($('#web2print_quantity').val()) || 1
            };
            
            // Mostrar loading
            $('#cost_result').html('<div class="calculating">' + web2print_ajax.texts.calculating + '</div>');
            
            $.ajax({
                url: web2print_ajax.ajax_url,
                type: 'POST',
                data: data,
                success: function(response) {
                    if (response.success) {
                        Web2PrintCalculator.displayCostResult(response.data);
                        $('#web2print_add_to_cart').prop('disabled', false);
                    } else {
                        Web2PrintCalculator.showError(response.data.message || web2print_ajax.texts.error);
                    }
                },
                error: function() {
                    Web2PrintCalculator.showError(web2print_ajax.texts.error);
                }
            });
        },
        
        displayCostResult: function(data) {
            var html = '<div class="cost-breakdown">';
            html += '<h4>💰 Cálculo de Custos</h4>';
            
            // Detalhamento
            html += '<table class="cost-table">';
            html += '<tr><td>📄 Impressão:</td><td>R$ ' + data.cost_details.pages_cost.toFixed(2) + '</td></tr>';
            html += '<tr><td>📚 Encadernação:</td><td>R$ ' + data.cost_details.binding_cost.toFixed(2) + '</td></tr>';
            
            if (data.cost_details.finishing_cost > 0) {
                html += '<tr><td>✨ Acabamentos:</td><td>R$ ' + data.cost_details.finishing_cost.toFixed(2) + '</td></tr>';
            }
            
            html += '<tr class="cost-subtotal"><td><strong>Subtotal por cópia:</strong></td><td><strong>R$ ' + data.cost_details.cost_per_copy.toFixed(2) + '</strong></td></tr>';
            html += '<tr><td>Quantidade:</td><td>' + data.cost_details.copy_quantity + 'x</td></tr>';
            html += '<tr class="cost-total"><td><strong>Total Final:</strong></td><td><strong>R$ ' + data.cost_details.total_cost.toFixed(2) + '</strong></td></tr>';
            html += '</table>';
            
            // Informações da configuração
            html += '<div class="config-summary">';
            html += '<h5>📋 Configuração Escolhida:</h5>';
            html += '<p><strong>Papel:</strong> ' + data.breakdown.paper_info + '</p>';
            html += '<p><strong>Encadernação:</strong> ' + data.breakdown.binding_info + '</p>';
            
            if (data.breakdown.finishing_info) {
                html += '<p><strong>Acabamentos:</strong> ' + data.breakdown.finishing_info + '</p>';
            }
            
            html += '</div>';
            html += '</div>';
            
            $('#cost_result').html(html);
            
            // Não manipular DOM do preço - WooCommerce gerenciará via hooks
        },
        
        getSelectedFinishing: function() {
            var finishing = [];
            $('.finishing-option:checked').each(function() {
                finishing.push($(this).val());
            });
            return finishing.join(',');
        },
        
        addToCart: function(e) {
            e.preventDefault();
            
            var colorPages = parseInt($('#color_pages').val()) || 0;
            var monoPages = parseInt($('#mono_pages').val()) || 0;
            
            if (colorPages === 0 && monoPages === 0) {
                Web2PrintCalculator.showError('Por favor, faça upload de um arquivo PDF primeiro.');
                return;
            }
            
            // Recalcular para garantir dados atualizados
            Web2PrintCalculator.calculateCost();
            
            // Aguardar um momento para o cálculo completar
            setTimeout(function() {
                // Usar o formulário padrão do WooCommerce
                $('form.cart').submit();
            }, 1000);
        },
        
        showError: function(message) {
            $('#cost_result').html('<div class="error-message">⚠️ ' + message + '</div>');
            $('#web2print_add_to_cart').prop('disabled', true);
        },
        
        formatBytes: function(bytes, decimals = 2) {
            if (bytes === 0) return '0 Bytes';
            
            const k = 1024;
            const dm = decimals < 0 ? 0 : decimals;
            const sizes = ['Bytes', 'KB', 'MB', 'GB'];
            
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            
            return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
        }
    };
    
    // Inicializar calculadora
    Web2PrintCalculator.init();
});