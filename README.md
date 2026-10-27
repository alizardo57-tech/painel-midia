# Painel de Mídia LED — Gerenciador de Propagandas

Aplicativo completo para gerenciar, agendar e exibir vídeos e imagens em **Painéis de LED**, TVs corporativas e TV Boxes.

## 🚀 Como usar no Computador (1 Clique)

1. Na pasta do projeto (ou no atalho na Área de Trabalho), dê dois cliques em **`INICIAR_PAINEL.bat`**.
2. O sistema abrirá automaticamente no navegador em **`http://localhost:5000`**.
3. Digite a senha padrão: **`trocar123`** (você pode alterar a senha dentro do painel no botão **⚙️ Senha e Empresa**).
4. Se o Painel de LED estiver ligado direto neste computador via cabo HDMI/Controladora, clique duas vezes em **`ABRIR_PLAYER_TELA_CHEIA.bat`** para abrir o reprodutor automático sem bordas.

## 📺 Como exibir na TV Box ou Controladora do Painel LED

1. No Painel Administrativo, copie o **Link para abrir no Painel LED / TV Box** (ou escaneie o **QR Code**).
2. Abra esse endereço no navegador da TV Box / Controladora do Painel.
3. Dê dois cliques na tela (ou clique em **⛶ Tela Cheia**) para ocupar 100% do painel.
4. O player possui **Cache Offline Inteligente**: uma vez carregados os vídeos, mesmo que a internet oscile ou caia, as propagandas continuam rodando sem tela preta!

## ✨ Recursos Inclusos

- **Upload com Barra de Progresso Real**: envie um ou vários vídeos (MP4, MOV, WEBM) e imagens (JPG, PNG, WEBP, GIF) com detecção automática do tempo do vídeo.
- **Gestão de Clientes e Campanhas**: cadastre o nome do anunciante, data de início, data de vencimento e horário de exibição. Campanhas vencidas saem do ar sozinhas.
- **Pausar/Ativar Propagandas**: pause um vídeo temporariamente sem precisar excluí-lo.
- **Ajustes Específicos para Painel LED**:
  - **Cover (Preencher sem bordas)**, **Fill (Esticar 100% na resolução do LED)** ou **Contain (Inteiro com bordas)**.
  - **Rotação de Tela** (0° Horizontal, 90°/270° Vertical para totens e painéis em pé, 180°).
  - **Transição suave** sem piscar tela preta entre vídeos.
- **Preview Ao Vivo**: veja como o painel LED está reproduzindo diretamente de dentro do painel de controle.

## ☁️ Como publicar na Nuvem (Render, Railway, VPS ou Docker)

O projeto já inclui `Procfile`, `Dockerfile` e `render.yaml`:
- **Comando de início (Linux/Nuvem)**: `gunicorn -w 2 --threads 4 -b 0.0.0.0:$PORT app:app`
- **Variáveis de ambiente opcionais**:
  - `ADMIN_PASSWORD`: senha inicial (padrão `trocar123`)
  - `SECRET_KEY`: chave de sessão
  - `DATA_DIR`: caminho do disco persistente (ex: `/var/data`)
