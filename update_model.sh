#!/data/data/com.termux/files/usr/bin/bash
# =============================================================================
# update_model.sh — Управление моделями AI Orchestrator на Termux
# Model manager for AI Orchestrator on Termux
# =============================================================================
# Позволяет:
#   - переключать уровень квантования TinyLlama
#   - скачивать дополнительные модели
#   - удалять ненужные модели
#
# Allows:
#   - switching TinyLlama quantization levels
#   - downloading additional models
#   - removing unused models
# =============================================================================

set -euo pipefail

# --- Переменные / Variables ---
MODEL_DIR="$HOME/.cache/ctransformers"
LOG_FILE="$HOME/.cache/orchestrator.log"
HF_MIRROR="${HF_MIRROR:-https://huggingface.co}"

# TinyLlama 1.1B Chat GGUF variants
REPO="TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF"
declare -A TINYLLAMA_QUANTS=(
    ["Q2_K"]="tinyllama-1.1b-chat-v1.0.Q2_K.gguf"
    ["Q3_K_M"]="tinyllama-1.1b-chat-v1.0.Q3_K_M.gguf"
    ["Q3_K_S"]="tinyllama-1.1b-chat-v1.0.Q3_K_S.gguf"
    ["Q4_K_M"]="tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
    ["Q4_K_S"]="tinyllama-1.1b-chat-v1.0.Q4_K_S.gguf"
    ["Q5_K_M"]="tinyllama-1.1b-chat-v1.0.Q5_K_M.gguf"
    ["Q5_K_S"]="tinyllama-1.1b-chat-v1.0.Q5_K_S.gguf"
    ["Q6_K"]="tinyllama-1.1b-chat-v1.0.Q6_K.gguf"
    ["Q8_0"]="tinyllama-1.1b-chat-v1.0.Q8_0.gguf"
)

# Размеры примерные (MB) / Approximate sizes (MB)
declare -A QUANT_SIZES=(
    ["Q2_K"]="467"
    ["Q3_K_S"]="514"
    ["Q3_K_M"]="553"
    ["Q4_K_S"]="644"
    ["Q4_K_M"]="669"
    ["Q5_K_S"]="759"
    ["Q5_K_M"]="778"
    ["Q6_K"]="887"
    ["Q8_0"]="1150"
)

# Доступные модели / Available models
declare -A EXTRA_MODELS=(
    ["phi-2-Q4_K_M"]="TheBloke/phi-2-GGUF|phi-2.Q4_K_M.gguf|1700"
    ["stablelm-3b-4e1t-Q4_K_M"]="stabilityai/stablelm-3b-4e1t-q4_k_m-gguf|stablelm-3b-4e1t.q4_k_m.gguf|2000"
    ["gemma-2b-it-Q4_K_M"]="google/gemma-2b-it-gguf|gemma-2b-it.Q4_K_M.gguf|1600"
)

# --- Цвета / Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m'

# --- Функции / Functions ---

info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }

show_help() {
    echo ""
    echo -e "${CYAN}╔═══════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║  AI Orchestrator — Менеджер моделей            ║${NC}"
    echo -e "${CYAN}║  AI Orchestrator — Model Manager               ║${NC}"
    echo -e "${CYAN}╚═══════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  Использование / Usage:"
    echo -e "    ${YELLOW}bash update_model.sh list${NC}              — список моделей / list models"
    echo -e "    ${YELLOW}bash update_model.sh current${NC}           — текущая модель / current model"
    echo -e "    ${YELLOW}bash update_model.sh switch <QUANT>${NC}   — переключить квант / switch quant"
    echo -e "    ${YELLOW}bash update_model.sh download <QUANT>${NC} — скачать квант / download quant"
    echo -e "    ${YELLOW}bash update_model.sh extra${NC}             — доп. модели / extra models"
    echo -e "    ${YELLOW}bash update_model.sh extra <name>${NC}      — скачать доп. модель / download extra"
    echo -e "    ${YELLOW}bash update_model.sh remove <QUANT>${NC}    — удалить модель / remove model"
    echo -e "    ${YELLOW}bash update_model.sh cleanup${NC}           — удалить всё / remove all"
    echo ""
    echo -e "  Доступные кванты TinyLlama / Available TinyLlama quants:"
    for q in Q2_K Q3_K_S Q3_K_M Q4_K_S Q4_K_M Q5_K_S Q5_K_M Q6_K Q8_0; do
        local size="${QUANT_SIZES[$q]:-?}"
        echo -e "    ${WHITE}$q${NC}  (~${size} MB)"
    done
    echo ""
    echo -e "  Дополнительные модели / Extra models:"
    for name in "${!EXTRA_MODELS[@]}"; do
        IFS='|' read -r _ _ size <<< "${EXTRA_MODELS[$name]}"
        echo -e "    ${WHITE}$name${NC}  (~${size} MB)"
    done
    echo ""
}

download_file() {
    # Скачивает файл с HuggingFace / Downloads file from HuggingFace
    # $1 = repo_id, $2 = filename, $3 = destination
    local repo="$1"
    local filename="$2"
    local dest="$3"
    local url="${HF_MIRROR}/${repo}/resolve/main/${filename}"

    info "Скачивание: $filename / Downloading: $filename"
    info "URL: $url"

    if wget --progress=bar:force:noscroll -O "$dest" "$url" 2>&1; then
        local size
        size=$(stat -c%s "$dest" 2>/dev/null || stat -f%z "$dest" 2>/dev/null || echo "0")
        if [ "$size" -lt 10000000 ]; then
            err "Файл слишком мал ($size bytes) / File too small ($size bytes)"
            rm -f "$dest"
            return 1
        fi
        ok "Скачано: $filename ($(( size / 1048576 )) MB) / Downloaded: $filename"
        return 0
    else
        err "Ошибка скачивания / Download error"
        rm -f "$dest"
        return 1
    fi
}

list_models() {
    echo ""
    echo -e "${CYAN}=== Установленные модели / Installed models ===${NC}"
    echo ""

    local count=0
    for f in "$MODEL_DIR"/*.gguf; do
        if [ -f "$f" ]; then
            local name
            name=$(basename "$f")
            local size
            size=$(stat -c%s "$f" 2>/dev/null || stat -f%z "$f" 2>/dev/null || echo "0")
            local size_mb=$(( size / 1048576 ))

            # Определяем квант / Determine quant
            local quant="unknown"
            for q in "${!TINYLLAMA_QUANTS[@]}"; do
                if [[ "$name" == *"$q"* ]]; then
                    quant="$q"
                    break
                fi
            done

            # Помечаем текущую / Mark current
            local marker="  "
            # Находим симлинк / Find symlink target
            local current_name=""
            for f2 in "$MODEL_DIR"/*.gguf; do
                if [ -L "$f2" ] && [ "$(readlink -f "$f2")" = "$(readlink -f "$f")" ]; then
                    current_name=$(basename "$f2")
                    if [ "$f2" != "$f" ]; then
                        continue
                    fi
                fi
            done

            echo -e "  ${GREEN}•${NC} ${WHITE}$name${NC}"
            echo -e "    Квант / Quant: ${CYAN}$quant${NC}  |  Размер / Size: ${YELLOW}${size_mb} MB${NC}"
            count=$((count + 1))
        fi
    done

    if [ "$count" -eq 0 ]; then
        warn "Установленных моделей не найдено / No installed models found"
        info "Запустите: bash update_model.sh download Q4_K_M"
    else
        echo ""
        ok "Всего / Total: $count модель(ей) / model(s)"
        echo -e "  Директория / Directory: ${CYAN}$MODEL_DIR${NC}"
    fi
    echo ""
}

show_current() {
    echo ""
    info "Текущая модель / Current model:"
    echo ""

    local found=0
    for f in "$MODEL_DIR"/*.gguf; do
        if [ -f "$f" ]; then
            local name
            name=$(basename "$f")
            local size
            size=$(stat -c%s "$f" 2>/dev/null || stat -f%z "$f" 2>/dev/null || echo "0")
            local size_mb=$(( size / 1048576 ))
            echo -e "  ${GREEN}→${NC} ${WHITE}$name${NC} (${size_mb} MB)"
            found=1
        fi
    done

    if [ "$found" -eq 0 ]; then
        warn "Модель не найдена / Model not found"
    fi
    echo ""
}

switch_quant() {
    local quant="${1^^}" # uppercase

    if [ -z "$quant" ]; then
        err "Укажите квант: bash update_model.sh switch Q4_K_M"
        exit 1
    fi

    local filename="${TINYLLAMA_QUANTS[$quant]:-}"
    if [ -z "$filename" ]; then
        err "Неизвестный квант: $quant / Unknown quant: $quant"
        echo "Доступные / Available: ${!TINYLLAMA_QUANTS[*]}"
        exit 1
    fi

    local dest="$MODEL_DIR/$filename"

    # Скачиваем если нет / Download if missing
    if [ ! -f "$dest" ]; then
        info "Модель $quant не найдена, скачиваем... / Model $quant not found, downloading..."
        download_file "$REPO" "$filename" "$dest" || exit 1
    fi

    # Обновляем ссылку / Update symlink
    local link="$MODEL_DIR/tinyllama-current.gguf"
    rm -f "$link"
    ln -sf "$dest" "$link"

    ok "Переключено на $quant / Switched to $quant"
    ok "Путь / Path: $dest"
    echo ""
    info "Перезапустите сервер для применения / Restart server to apply"
}

download_quant() {
    local quant="${1^^}"

    if [ -z "$quant" ]; then
        err "Укажите квант: bash update_model.sh download Q4_K_M"
        exit 1
    fi

    local filename="${TINYLLAMA_QUANTS[$quant]:-}"
    if [ -z "$filename" ]; then
        err "Неизвестный квант: $quant / Unknown quant: $quant"
        exit 1
    fi

    local dest="$MODEL_DIR/$filename"
    if [ -f "$dest" ]; then
        ok "Модель уже скачана: $filename / Model already downloaded: $filename"
        return 0
    fi

    download_file "$REPO" "$filename" "$dest" || exit 1
}

show_extra() {
    echo ""
    echo -e "${CYAN}=== Дополнительные модели / Extra models ===${NC}"
    echo ""

    for name in $(echo "${!EXTRA_MODELS[@]}" | tr ' ' '\n' | sort); do
        IFS='|' read -r repo filename size <<< "${EXTRA_MODELS[$name]}"
        local status="${RED}не скачана / not downloaded${NC}"

        if [ -f "$MODEL_DIR/$filename" ]; then
            status="${GREEN}установлена / installed${NC}"
        fi

        echo -e "  ${WHITE}$name${NC}  (~${size} MB)"
        echo -e "    Репозиторий / Repo: $repo"
        echo -e "    Файл / File: $filename"
        echo -e "    Статус / Status: $status"
        echo ""
    done
}

download_extra() {
    local name="${1:-}"

    if [ -z "$name" ]; then
        err "Укажите модель: bash update_model.sh extra <name>"
        echo "Доступные / Available:"
        for n in "${!EXTRA_MODELS[@]}"; do
            echo "  $n"
        done
        exit 1
    fi

    local model_data="${EXTRA_MODELS[$name]:-}"
    if [ -z "$model_data" ]; then
        err "Неизвестная модель: $name / Unknown model: $name"
        exit 1
    fi

    IFS='|' read -r repo filename size <<< "$model_data"
    local dest="$MODEL_DIR/$filename"

    if [ -f "$dest" ]; then
        ok "Модель уже скачана: $filename / Model already downloaded"
        return 0
    fi

    download_file "$repo" "$filename" "$dest" || exit 1
}

remove_model() {
    local quant="${1:-}"

    if [ -z "$quant" ]; then
        # Интерактивное удаление / Interactive removal
        echo ""
        warn "Укажите квант для удаления / Specify quant to remove"
        echo ""
        for f in "$MODEL_DIR"/*.gguf; do
            [ -f "$f" ] || continue
            local name
            name=$(basename "$f")
            local size
            size=$(stat -c%s "$f" 2>/dev/null || stat -f%z "$f" 2>/dev/null || echo "0")
            local size_mb=$(( size / 1048576 ))
            echo "  $name  (${size_mb} MB)"
        done
        echo ""
        echo "Пример / Example: bash update_model.sh remove Q3_K_M"
        echo "Для удаления всех: bash update_model.sh cleanup"
        return 1
    fi

    local filename="${TINYLLAMA_QUANTS[$quant]:-}"
    if [ -z "$filename" ]; then
        # Пробуем как имя файла / Try as filename
        filename="$quant"
    fi

    local target="$MODEL_DIR/$filename"

    # Если передан квант, ищем по маске / If quant given, search by pattern
    if [ -n "${TINYLLAMA_QUANTS[$quant]:-}" ]; then
        target="$MODEL_DIR/$filename"
    else
        # Ищем по паттерну в имени / Search by name pattern
        for f in "$MODEL_DIR"/*"$quant"*.gguf; do
            if [ -f "$f" ]; then
                target="$f"
                break
            fi
        done
    fi

    if [ ! -f "$target" ]; then
        err "Файл не найден: $target / File not found"
        return 1
    fi

    local name
    name=$(basename "$target")

    read -r -p "Удалить $name? [y/N] " answer
    if [[ "$answer" =~ ^[Yy] ]]; then
        rm -f "$target"
        # Удаляем симлинки / Remove symlinks
        for f in "$MODEL_DIR"/*.gguf; do
            if [ -L "$f" ] && [ ! -e "$f" ]; then
                rm -f "$f"
            fi
        done
        ok "Удалено: $name / Removed: $name"
    else
        info "Отмена / Cancelled"
    fi
}

cleanup_all() {
    echo ""
    warn "Это удалит ВСЕ скачанные модели / This will remove ALL downloaded models"
    echo ""
    list_models

    read -r -p "Вы уверены? [y/N] " answer
    if [[ "$answer" =~ ^[Yy] ]]; then
        rm -f "$MODEL_DIR"/*.gguf
        rm -f "$MODEL_DIR"/*.gguf.*
        ok "Все модели удалены / All models removed"
    else
        info "Отмена / Cancelled"
    fi
}

# --- Основной поток / Main flow ---

main() {
    mkdir -p "$MODEL_DIR"

    local cmd="${1:-help}"
    shift 2>/dev/null || true

    case "$cmd" in
        list|ls)
            list_models
            ;;
        current|show|status)
            show_current
            ;;
        switch|sw)
            switch_quant "${1:-}"
            ;;
        download|dl)
            download_quant "${1:-}"
            ;;
        extra|add)
            if [ -z "${1:-}" ]; then
                show_extra
            else
                download_extra "$1"
            fi
            ;;
        remove|rm|delete)
            remove_model "${1:-}"
            ;;
        cleanup|clean)
            cleanup_all
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            err "Неизвестная команда: $cmd / Unknown command: $cmd"
            show_help
            exit 1
            ;;
    esac
}

main "$@"
