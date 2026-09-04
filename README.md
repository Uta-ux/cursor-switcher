# Trocador de Cursor

Seletor de temas de cursor do mouse para GNOME, em GTK4 + libadwaita.

Mostra todos os temas de cursor instalados numa grade de cartões com
pré-visualização real — os ponteiros desenhados no cartão são lidos do próprio
arquivo XCursor do tema, não são imagens genéricas. Escolher um cartão aplica o
tema na hora.

## O que ele faz

- Lista os temas encontrados em `~/.icons`, `~/.local/share/icons`,
  `/usr/local/share/icons` e `/usr/share/icons`
- Pré-visualiza cinco ponteiros de cada tema (seta, mãozinha, texto, ampulheta
  e "não permitido"), com fallback entre os nomes alternativos de cada um
- Aplica o tema e o tamanho do cursor via `gsettings`, na chave
  `org.gnome.desktop.interface`
- Instala temas novos a partir de arquivos `.zip` ou `.tar.*`, direto em
  `~/.local/share/icons`
- Remove temas instalados pelo usuário

Tamanhos disponíveis: 24, 28, 32, 38 e 48 px.

## Requisitos

- Python 3.10 ou mais novo
- GTK 4 + libadwaita via PyGObject

No Ubuntu/Debian:

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
```

## Instalação

```bash
git clone https://github.com/Uta-ux/cursor-switcher.git
cd cursor-switcher
./install.sh
```

O `install.sh` copia o executável para `~/.local/bin/` e cria o lançador em
`~/.local/share/applications/`, então o app passa a aparecer no menu de
aplicativos. Para remover, rode `./uninstall.sh`.

## Detalhe de implementação

O leitor de XCursor é próprio (`parse_xcursor`): percorre o TOC do arquivo,
pega a imagem de tamanho nominal mais próximo do pedido e converte de ARGB32
pré-multiplicado little-endian para o RGBA que o GdkPixbuf espera. É isso que
permite a pré-visualização fiel sem depender de biblioteca externa.

## Licença

[MIT](LICENSE).
