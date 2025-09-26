# Configurar API_KEY no environment do Flask
export API_KEY="sua_chave_secura_aqui"

# Fazer requisição
curl -X POST "https://seu-dominio.com/api/v1/calculate_final" \
-H "Content-Type: application/json" \
-H "X-API-Key: sua_chave_secura_aqui" \
-d '{
  "color_pages": 5,
  "mono_pages": 10,
  "paper_type": "sulfite",
  "binding_type": "spiral",
  "copy_quantity": 2
}'