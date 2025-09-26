# Web2Print WordPress Plugin

Plugin de integração para WooCommerce que conecta com a API Web2Print para cálculo avançado de custos de impressão.

## 📦 Instalação

1. **Upload do Plugin:**
   - Faça upload da pasta `wordpress-plugin` para `/wp-content/plugins/web2print-integration/`
   - Ou compacte os arquivos em ZIP e instale via admin WordPress

2. **Ativação:**
   - Acesse `Plugins > Plugins Instalados` no admin WordPress
   - Ative o plugin "Web2Print WooCommerce Integration"

3. **Configuração:**
   - Vá para `Configurações > Web2Print`
   - Configure o endpoint da API: `https://seu-dominio.com/api/v1/calculate_final`
   - Configure a chave da API (X-API-Key)

4. **Configuração do Produto:**
   - Edite um produto WooCommerce
   - Na seção "Dados do Produto", adicione um campo personalizado:
     - Meta Key: `_enable_web2print`
     - Meta Value: `yes`

## 🎯 Funcionalidades

- ✅ **Upload de PDF com drag & drop**
- ✅ **Análise automática de páginas coloridas/monocromáticas**
- ✅ **Configuração de papel, encadernação e acabamentos**
- ✅ **Cálculo em tempo real via API**
- ✅ **Integração completa com carrinho WooCommerce**
- ✅ **Forçar preço calculado no checkout**
- ✅ **Salvar metadados do pedido**

## 🔧 Como Usar

1. Cliente acessa produto com Web2Print habilitado
2. Faz upload do arquivo PDF
3. Configura opções de impressão
4. Vê cálculo em tempo real
5. Adiciona ao carrinho com preço correto
6. Finaliza pedido com metadados salvos

## 🔌 Hooks Utilizados

- `woocommerce_single_product_summary` - Exibe calculadora
- `woocommerce_before_calculate_totals` - Força preço calculado
- `woocommerce_add_to_cart` - Salva metadados
- `wp_ajax_web2print_calculate` - Processamento AJAX

## 📋 Requisitos

- WordPress 5.0+
- WooCommerce 4.0+
- PHP 7.4+
- API Web2Print configurada e funcionando