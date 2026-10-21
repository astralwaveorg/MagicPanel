#!/bin/bash
# bash -c "$(curl -fsSL https://magichub.top/download/scripts/install-vim.sh)"
set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 检测操作系统
detect_os() {
	if [[ "$OSTYPE" == "linux-gnu"* ]]; then
		if [ -f /etc/os-release ]; then
			. /etc/os-release
			OS=$NAME
		else
			OS=$(uname -s)
		fi
	elif [[ "$OSTYPE" == "darwin"* ]]; then
		OS="macOS"
	else
		log_error "不支持的操作系统: $OSTYPE"
		exit 1
	fi
	log_info "检测到操作系统: $OS"
}

# 安装基础依赖
install_dependencies() {
	log_info "安装系统依赖..."

	if [[ "$OS" == "Ubuntu" || "$OS" == "Debian"* ]]; then
		sudo apt update
		sudo apt install -y curl wget git build-essential
		sudo apt install -y python3 python3-pip python3-venv
		sudo apt install -y nodejs npm
		sudo apt install -y exuberant-ctags silversearcher-ag
		sudo apt install -y vim-gtk3 neovim

		# 如果系统Node.js版本太老，使用NodeSource仓库
		if ! command -v node &>/dev/null || [ $(node -v | cut -d'.' -f1 | sed 's/v//') -lt 14 ]; then
			log_info "安装更新的Node.js版本..."
			curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
			sudo apt install -y nodejs
		fi

	elif [[ "$OS" == "macOS" ]]; then
		# 检查是否安装了Homebrew
		if ! command -v brew &>/dev/null; then
			log_info "安装Homebrew..."
			/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
		fi

		brew update
		brew install curl wget git python3 nodejs
		brew install universal-ctags the_silver_searcher
		brew install vim neovim

	else
		log_error "不支持的操作系统: $OS"
		exit 1
	fi
}

# 安装Python依赖
install_python_deps() {
	log_info "安装Python依赖..."

	# 配置pip镜像源
	mkdir -p ~/.pip
	cat >~/.pip/pip.conf <<'EOF'
[global]
index-url = https://pypi.tuna.tsinghua.edu.cn/simple
extra-index-url = https://mirrors.aliyun.com/pypi/simple/
trusted-host =
    pypi.tuna.tsinghua.edu.cn
    mirrors.aliyun.com
timeout = 60
retries = 3
EOF

	# 安装Python包
	pip3 install --upgrade pip
	pip3 install pynvim black isort flake8 pylint
	pip3 install requests numpy pandas jupyter

	log_success "Python依赖安装完成"
}

# 安装Node.js依赖
install_node_deps() {
	log_info "安装Node.js依赖..."

	# 配置npm镜像源
	npm config set registry https://registry.npmmirror.com
	npm config set disturl https://npmmirror.com/dist

	# 安装全局包
	sudo npm install -g neovim
	sudo npm install -g typescript prettier eslint

	log_success "Node.js依赖安装完成"
}

# 安装Go工具（如果系统安装了Go）
install_go_tools() {
	if command -v go &>/dev/null; then
		log_info "安装Go开发工具..."
		go install github.com/golang/tools/gopls@latest
		go install github.com/segmentio/golines@latest
		log_success "Go工具安装完成"
	else
		log_warning "未检测到Go语言环境，跳过Go工具安装"
	fi
}

# 备份现有配置
backup_existing_config() {
	if [ -f ~/.vimrc ]; then
		backup_name=".vimrc.backup.$(date +%Y%m%d_%H%M%S)"
		mv ~/.vimrc ~/$backup_name
		log_info "已备份现有配置: ~/$backup_name"
	fi

	if [ -d ~/.vim ]; then
		backup_name=".vim.backup.$(date +%Y%m%d_%H%M%S)"
		mv ~/.vim ~/$backup_name
		log_info "已备份现有配置: ~/$backup_name"
	fi

	if [ -d ~/.config/nvim ]; then
		backup_name="nvim.backup.$(date +%Y%m%d_%H%M%S)"
		mv ~/.config/nvim ~/.config/$backup_name
		log_info "已备份现有配置: ~/.config/$backup_name"
	fi
}

# 下载Vim配置
download_vim_config() {
	log_info "下载Vim配置文件..."

	# 尝试从多个源下载配置
	local config_url="https://magichub.top/download/config/vimrc"
	local fallback_url="https://raw.githubusercontent.com/junegunn/vim-plug/master/plug.vim"

	if command -v curl &>/dev/null; then
		if curl -fsSL -o ~/.vimrc "$config_url"; then
			log_success "从主源下载配置成功"
		else
			log_warning "主源下载失败，使用备用配置"
			create_fallback_config
		fi
	elif command -v wget &>/dev/null; then
		if wget -q -O ~/.vimrc "$config_url"; then
			log_success "从主源下载配置成功"
		else
			log_warning "主源下载失败，使用备用配置"
			create_fallback_config
		fi
	else
		log_warning "无法下载配置，创建基础配置"
		create_fallback_config
	fi
}

# 创建备用配置（如果下载失败）
create_fallback_config() {
	cat >~/.vimrc <<'EOF'
" 基础Vim配置
set nocompatible
filetype off

" 插件管理
call plug#begin('~/.vim/plugged')
Plug 'morhetz/gruvbox'
Plug 'vim-airline/vim-airline'
Plug 'preservim/nerdtree'
Plug 'sheerun/vim-polyglot'
Plug 'neoclide/coc.nvim', {'branch': 'release'}
Plug 'dense-analysis/ale'
Plug 'tpope/vim-commentary'
Plug 'tpope/vim-surround'
call plug#end()

" 基础设置
syntax enable
filetype plugin indent on
set number
set expandtab
set tabstop=4
set shiftwidth=4
set smartindent
set incsearch
set hlsearch
set ignorecase
set smartcase

" 主题
colorscheme gruvbox
set background=dark

" 快捷键
let mapleader=","
nmap <leader>s :w<CR>
nmap <leader>q :q<CR>
nmap <leader>wq :wq<CR>
nmap <leader>f :NERDTreeToggle<CR>

" 创建必要目录
silent! call system('mkdir -p ~/.vim/undodir ~/.vim/backup ~/.vim/swap')
EOF
	log_info "已创建备用Vim配置"
}

# 安装vim-plug插件管理器
install_vim_plug() {
	log_info "安装vim-plug插件管理器..."

	# 安装Vim版的vim-plug
	curl -fLo ~/.vim/autoload/plug.vim --create-dirs \
		https://raw.githubusercontent.com/junegunn/vim-plug/master/plug.vim

	# 安装Neovim版的vim-plug
	if command -v nvim &>/dev/null; then
		sh -c 'curl -fLo "${XDG_DATA_HOME:-$HOME/.local/share}"/nvim/site/autoload/plug.vim --create-dirs \
            https://raw.githubusercontent.com/junegunn/vim-plug/master/plug.vim'
	fi

	log_success "vim-plug安装完成"
}

# 创建必要目录
create_directories() {
	log_info "创建必要的目录结构..."

	mkdir -p ~/.vim/undodir
	mkdir -p ~/.vim/backup
	mkdir -p ~/.vim/swap
	mkdir -p ~/.config/nvim

	# 创建Neovim符号链接
	if command -v nvim &>/dev/null; then
		ln -sf ~/.vimrc ~/.config/nvim/init.vim
	fi

	log_success "目录结构创建完成"
}

# 安装Vim插件
install_vim_plugins() {
	log_info "开始安装Vim插件..."

	# 设置超时和重试环境变量
	export PLUG_TIMEOUT=300
	export GIT_TERMINAL_PROMPT=1

	# 安装插件
	if command -v nvim &>/dev/null; then
		log_info "使用Neovim安装插件..."
		nvim +PlugInstall +qall
	else
		log_info "使用Vim安装插件..."
		vim +PlugInstall +qall
	fi

	# 如果安装失败，尝试重试
	if [ $? -ne 0 ]; then
		log_warning "插件安装可能不完整，尝试重新安装..."
		if command -v nvim &>/dev/null; then
			nvim +PlugClean! +PlugInstall +qall
		else
			vim +PlugClean! +PlugInstall +qall
		fi
	fi

	log_success "Vim插件安装完成"
}

# 安装coc.nvim扩展
install_coc_extensions() {
	log_info "安装coc.nvim扩展..."

	# 创建coc-settings.json
	mkdir -p ~/.config/nvim
	cat >~/.config/nvim/coc-settings.json <<'EOF'
{
  "coc.preferences.formatOnSaveFiletypes": ["javascript", "typescript", "python", "go", "yaml", "json", "html", "css", "markdown"],
  "python.pythonPath": "python3",
  "python.linting.enabled": true,
  "python.linting.pylintEnabled": true,
  "python.formatting.provider": "black",
  "go.goplsPath": "gopls",
  "languageserver": {
    "golang": {
      "command": "gopls",
      "rootPatterns": ["go.mod", ".vim/", ".git/", ".hg/"],
      "filetypes": ["go"]
    }
  }
}
EOF

	# 安装coc扩展
	if command -v nvim &>/dev/null; then
		nvim +"CocInstall coc-json coc-yaml coc-pyright coc-html coc-css coc-tsserver" +qall
	else
		vim +"CocInstall coc-json coc-yaml coc-pyright coc-html coc-css coc-tsserver" +qall
	fi

	log_success "coc.nvim扩展安装完成"
}

# 配置Git（可选）
setup_git_config() {
	if command -v git &>/dev/null; then
		log_info "配置Git..."

		# 设置基本的Git配置（如果尚未设置）
		if [ -z "$(git config --global user.name)" ]; then
			git config --global user.name "Vim User"
			git config --global user.email "vim@example.com"
		fi

		git config --global init.defaultBranch main
		git config --global core.editor "vim"

		log_success "Git配置完成"
	fi
}

# 验证安装
verify_installation() {
	log_info "验证安装..."

	echo ""
	echo "=== 安装验证 ==="

	# 检查Vim/Neovim
	if command -v vim &>/dev/null; then
		echo "✅ Vim 已安装: $(vim --version | head -1)"
	else
		echo "❌ Vim 未安装"
	fi

	if command -v nvim &>/dev/null; then
		echo "✅ Neovim 已安装: $(nvim --version | head -1)"
	else
		echo "❌ Neovim 未安装"
	fi

	# 检查Node.js
	if command -v node &>/dev/null; then
		echo "✅ Node.js 已安装: $(node --version)"
	else
		echo "❌ Node.js 未安装"
	fi

	# 检查Python
	if command -v python3 &>/dev/null; then
		echo "✅ Python3 已安装: $(python3 --version)"
	else
		echo "❌ Python3 未安装"
	fi

	# 检查配置文件
	if [ -f ~/.vimrc ]; then
		echo "✅ Vim配置已安装"
	else
		echo "❌ Vim配置未安装"
	fi

	if [ -d ~/.vim/plugged ]; then
		plugin_count=$(find ~/.vim/plugged -maxdepth 1 -type d | wc -l)
		echo "✅ Vim插件已安装 (数量: $((plugin_count - 1)))"
	else
		echo "❌ Vim插件未安装"
	fi

	echo ""
}

# 显示使用说明
show_usage() {
	echo ""
	echo "=================== Vim 配置安装完成 ==================="
	echo ""
	echo "🎉 安装已完成！以下是一些使用提示："
	echo ""
	echo "📖 快捷键帮助:"
	echo "   在Vim中输入 ',help' 查看完整的快捷键指南"
	echo ""
	echo "🔧 常用命令:"
	echo "   vim                    # 启动Vim"
	echo "   nvim                   # 启动Neovim"
	echo "   vim +PlugInstall       # 重新安装插件"
	echo "   vim +PlugUpdate        # 更新插件"
	echo "   vim +CocUpdate         # 更新coc扩展"
	echo ""
	echo "📁 配置文件位置:"
	echo "   ~/.vimrc               # Vim主配置"
	echo "   ~/.vim/plugged/        # 插件目录"
	echo "   ~/.config/nvim/        # Neovim配置目录"
	echo ""
	echo "🐛 问题排查:"
	echo "   1. 如果插件安装失败，运行: vim +PlugInstall"
	echo "   2. 查看插件状态: vim +PlugStatus"
	echo "   3. 清理未使用的插件: vim +PlugClean"
	echo ""
	echo "======================================================"
	echo ""
}

# 主函数
main() {
	echo ""
	echo "================================================"
	echo "           Vim 环境全自动安装脚本"
	echo "================================================"
	echo ""

	# 检测操作系统
	detect_os

	# 安装依赖
	install_dependencies

	# 安装语言相关工具
	install_python_deps
	install_node_deps
	install_go_tools

	# 备份现有配置
	backup_existing_config

	# 安装vim-plug
	install_vim_plug

	# 创建目录结构
	create_directories

	# 下载配置
	download_vim_config

	# 安装插件
	install_vim_plugins

	# 安装coc扩展
	install_coc_extensions

	# 配置Git
	setup_git_config

	# 验证安装
	verify_installation

	# 显示使用说明
	show_usage
}

# 运行主函数
main "$@"
