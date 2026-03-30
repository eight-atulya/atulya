#!/usr/bin/env bash

set -Eeuo pipefail

# =============================================================================
# [root] PALETTE — PRIMARY COLORS ONLY
# Deep Red | Bright Yellow | Black | White | Green
# =============================================================================
HAS_COLOR=false
TERM_COLORS=0
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && command -v tput >/dev/null 2>&1; then
  TERM_COLORS="$(tput colors 2>/dev/null || echo 0)"
  if [ "$TERM_COLORS" -ge 8 ]; then
    HAS_COLOR=true
  fi
fi

NC=''
BOLD=''
DIM=''
UNDERLINE=''
ITALIC=''

RED=''
BR_RED=''
GREEN=''
BR_GREEN=''
YELLOW=''
BR_YELLOW=''
WHITE=''
GRAY=''

BG_RED=''
BG_GREEN=''
BG_YELLOW=''

CURSOR_HIDE=''
CURSOR_SHOW=''
CLEAR_LINE=''

if [ "$HAS_COLOR" = true ]; then
  NC='\033[0m'
  BOLD='\033[1m'
  DIM='\033[2m'
  UNDERLINE='\033[4m'
  ITALIC='\033[3m'
  CURSOR_HIDE='\033[?25l'
  CURSOR_SHOW='\033[?25h'
  CLEAR_LINE='\033[2K'

  if [ "$TERM_COLORS" -ge 256 ]; then
    RED='\033[38;5;160m'
    BR_RED='\033[38;5;196m'
    GREEN='\033[38;5;70m'
    BR_GREEN='\033[38;5;120m'
    YELLOW='\033[38;5;214m'
    BR_YELLOW='\033[38;5;209m'
    WHITE='\033[38;5;255m'
    GRAY='\033[38;5;245m'
    BG_RED='\033[48;5;52m'
    BG_GREEN='\033[48;5;22m'
    BG_YELLOW='\033[48;5;58m'
  else
    RED='\033[31m'
    BR_RED='\033[91m'
    GREEN='\033[32m'
    BR_GREEN='\033[92m'
    YELLOW='\033[33m'
    BR_YELLOW='\033[93m'
    WHITE='\033[97m'
    GRAY='\033[90m'
    BG_RED='\033[41m'
    BG_GREEN='\033[42m'
    BG_YELLOW='\033[43m'
  fi
fi

TERM_WIDTH="$(tput cols 2>/dev/null || echo 80)"
if [ "$TERM_WIDTH" -lt 60 ]; then
  TERM_WIDTH=60
fi
ATULYA_VERSION="3.0"

# =============================================================================
# [trunk] ANIMATION ENGINE — Spinner + Mechanical Feedback
# =============================================================================
SPINNER_PID=""
SPINNER_FRAMES=('/' '-' '\' '|' '/' '-' '\' '|')

_cleanup_spinner() {
  if [ -n "$SPINNER_PID" ] && kill -0 "$SPINNER_PID" 2>/dev/null; then
    kill "$SPINNER_PID" 2>/dev/null
    wait "$SPINNER_PID" 2>/dev/null || true
    SPINNER_PID=""
  fi
  printf '%b%b' "$CLEAR_LINE" "$CURSOR_SHOW"
}
trap _cleanup_spinner EXIT

spinner_start() {
  local msg="${1:-Working...}"
  if [ "$HAS_COLOR" = false ]; then printf '  %s\n' "$msg"; return; fi
  printf '%b' "$CURSOR_HIDE"
  (
    local i=0
    while true; do
      printf '\r%b  %b[%s]%b %b%s%b' \
        "$CLEAR_LINE" "$BR_RED" "${SPINNER_FRAMES[$((i % ${#SPINNER_FRAMES[@]}))]}" "$NC" \
        "$GRAY" "$msg" "$NC"
      i=$((i + 1))
      sleep 0.1
    done
  ) &
  SPINNER_PID=$!
}

spinner_stop() {
  local result_msg="${1:-Done}" icon="${2:-[VALID]}" color="${3:-$GREEN}"
  if [ -n "$SPINNER_PID" ] && kill -0 "$SPINNER_PID" 2>/dev/null; then
    kill "$SPINNER_PID" 2>/dev/null
    wait "$SPINNER_PID" 2>/dev/null || true
    SPINNER_PID=""
    printf '\r%b  %b%s%b %s\n' "$CLEAR_LINE" "$color" "$icon" "$NC" "$result_msg"
    printf '%b' "$CURSOR_SHOW"
  else
    printf '  %s %s\n' "$icon" "$result_msg"
  fi
}

# Typewriter — mechanical keystroke effect
typewriter() {
  local text="$1" color="${2:-$NC}" speed="${3:-0.012}"
  if [ "$HAS_COLOR" = false ]; then printf '  %s\n' "$text"; return; fi
  printf '  '
  local i
  for ((i = 0; i < ${#text}; i++)); do
    printf '%b%s%b' "$color" "${text:$i:1}" "$NC"
    sleep "$speed"
  done
  printf '\n'
}

# Box-drawing horizontal rule
hr() {
  local label="${1:-}" color="${2:-$GRAY}"
  local width=$((TERM_WIDTH > 80 ? 76 : TERM_WIDTH - 4))
  if [ -n "$label" ]; then
    local label_len=${#label}
    local side=$(( (width - label_len - 4) / 2 ))
    local left="" right=""
    local i
    for ((i = 0; i < side; i++)); do left+="─"; done
    for ((i = 0; i < side; i++)); do right+="─"; done
    printf '  %b%s┤%b %b%s%b %b├%s%b\n' \
      "$color" "$left" "$NC" "$WHITE$BOLD" "$label" "$NC" "$color" "$right" "$NC"
  else
    local line=""
    local i
    for ((i = 0; i < width; i++)); do line+="─"; done
    printf '  %b%s%b\n' "$color" "$line" "$NC"
  fi
}

# =============================================================================
# [leaf] LOGGING — greppable, industrial
# =============================================================================
log_info()  { printf '  %b[INFO]%b  %s\n'  "$BR_RED"    "$NC" "$1"; }
log_warn()  { printf '  %b[WARN]%b  %s\n'  "$YELLOW"    "$NC" "$1"; }
log_error() { printf '  %b[ERROR]%b %s\n'  "$RED"       "$NC" "$1"; }
log_ok()    { printf '  %b[VALID]%b %s\n'  "$GREEN"     "$NC" "$1"; }

die() { log_error "$1"; exit "${2:-1}"; }

# =============================================================================
# [branch] ARGUMENT PARSING
# =============================================================================
OUTPUT_DIR=""
OUTPUT_FILENAME=""
SCOPE=""
GIT_RANGE=""
INCLUDE_DIFF=true
INCLUDE_STATS=true
INTERACTIVE=true

show_help() {
  printf '\n'
  printf '  %b%batulya-git%b %bv%s%b\n' "$BR_RED" "$BOLD" "$NC" "$GRAY" "$ATULYA_VERSION" "$NC"
  printf '  %bCortex-grade git memory synthesis for Atulya development sessions%b\n\n' "$GRAY" "$NC"
  printf '  %bUSAGE%b\n' "$UNDERLINE" "$NC"
  printf '    ./session-changelog.sh [OPTIONS]\n\n'
  printf '  %bSCOPES%b\n' "$UNDERLINE" "$NC"
  printf '    unstaged         Working tree modifications not yet staged\n'
  printf '    staged           Changes in the index ready to commit\n'
  printf '    all-uncommitted  staged + unstaged + untracked\n'
  printf '    unpushed         Commits ahead of remote tracking branch\n'
  printf '    last-commit      Most recent commit only\n'
  printf '    last-n           Last N commits (use --range N)\n'
  printf '    since-tag        All commits since the latest tag\n'
  printf '    range            Custom ref range (use --range A..B)\n\n'
  printf '  %bOPTIONS%b\n' "$UNDERLINE" "$NC"
  printf '    %b--scope%b SCOPE        Select scope directly (skip menu)\n' "$BOLD" "$NC"
  printf '    %b--range%b REF          Range or count for scope\n' "$BOLD" "$NC"
  printf '    %b--output%b DIR         Output directory\n' "$BOLD" "$NC"
  printf '    %b--filename%b NAME      Output filename\n' "$BOLD" "$NC"
  printf '    %b--no-diff%b            Omit inline diffs\n' "$BOLD" "$NC"
  printf '    %b--no-stats%b           Omit file statistics\n' "$BOLD" "$NC"
  printf '    %b--no-interactive%b     CI/script mode (requires --scope)\n' "$BOLD" "$NC"
  printf '    %b--help%b               This help\n\n' "$BOLD" "$NC"
  printf '  %bEXAMPLES%b\n' "$UNDERLINE" "$NC"
  printf '    %b$%b ./session-changelog.sh\n' "$GREEN" "$NC"
  printf '    %b$%b ./session-changelog.sh --scope last-commit --no-interactive\n' "$GREEN" "$NC"
  printf '    %b$%b ./session-changelog.sh --scope range --range v0.8.0..HEAD\n' "$GREEN" "$NC"
  printf '    %b$%b ./session-changelog.sh --scope last-n --range 5 --no-diff\n\n' "$GREEN" "$NC"
  exit 0
}

while (($#)); do
  case "$1" in
    --output)         OUTPUT_DIR="${2:?Missing --output value}";     shift 2 ;;
    --filename)       OUTPUT_FILENAME="${2:?Missing --filename value}"; shift 2 ;;
    --scope)          SCOPE="${2:?Missing --scope value}";           shift 2 ;;
    --range)          GIT_RANGE="${2:?Missing --range value}";       shift 2 ;;
    --no-diff)        INCLUDE_DIFF=false;  shift ;;
    --no-stats)       INCLUDE_STATS=false; shift ;;
    --no-interactive) INTERACTIVE=false;   shift ;;
    --help|-h)        show_help ;;
    *)                die "Unknown flag: $1" 10 ;;
  esac
done

# =============================================================================
# [root] PROJECT AUTO-DETECTION + INTELLIGENCE
# =============================================================================
detect_project() {
  git rev-parse --show-toplevel 2>/dev/null || die "Not inside a git repository."
}

PROJECT_ROOT="$(detect_project)"
cd "$PROJECT_ROOT"

first_line() {
  sed -n '1p'
}

PROJECT_NAME="$(basename "$PROJECT_ROOT")"
CURRENT_BRANCH="$(git symbolic-ref --short -q HEAD 2>/dev/null || echo 'detached')"
REMOTE_NAME="$(git remote 2>/dev/null | first_line || true)"
LAST_TAG="$(git describe --tags --abbrev=0 2>/dev/null || echo 'none')"
HEAD_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
FULL_SHA="$(git rev-parse HEAD 2>/dev/null || echo 'unknown')"
HEAD_MSG="$(git log -1 --format='%s' 2>/dev/null || echo '')"
TOTAL_COMMITS="$(git rev-list --count HEAD 2>/dev/null || echo '0')"
CONTRIBUTORS="$(git shortlog -sn --no-merges HEAD 2>/dev/null | wc -l | tr -d ' ')"
REPO_BORN="$(git log --reverse --format='%ar' 2>/dev/null | first_line || true)"
if [ -z "$REPO_BORN" ]; then
  REPO_BORN="unknown"
fi
EMPTY_TREE_SHA="$(git hash-object -t tree /dev/null 2>/dev/null || echo '4b825dc642cb6eb9a060e54bf8d69288fbee4904')"
HAS_HEAD_PARENT=false
if git rev-parse HEAD~1 >/dev/null 2>&1; then
  HAS_HEAD_PARENT=true
fi

COUNT_UNSTAGED=$(git diff --name-only 2>/dev/null | wc -l | tr -d ' ')
COUNT_STAGED=$(git diff --cached --name-only 2>/dev/null | wc -l | tr -d ' ')
COUNT_UNTRACKED=$(git ls-files --others --exclude-standard 2>/dev/null | wc -l | tr -d ' ')
COUNT_TOTAL_DIRTY=$((COUNT_UNSTAGED + COUNT_STAGED + COUNT_UNTRACKED))

if [ "$CURRENT_BRANCH" != "detached" ]; then
  UPSTREAM="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || echo '')"
  if [ -n "$UPSTREAM" ]; then
    COUNT_UNPUSHED="$(git rev-list "${UPSTREAM}..HEAD" --count 2>/dev/null || echo "0")"
  else
    COUNT_UNPUSHED="N/A"
  fi
else
  UPSTREAM=""
  COUNT_UNPUSHED="N/A"
fi

# Session complexity score (0-100)
_compute_complexity() {
  local score=0
  score=$((score + COUNT_UNSTAGED * 3))
  score=$((score + COUNT_STAGED * 3))
  score=$((score + COUNT_UNTRACKED * 2))
  if [ "$COUNT_UNPUSHED" != "N/A" ]; then
    score=$((score + COUNT_UNPUSHED * 5))
  fi
  if [ "$score" -gt 100 ]; then score=100; fi
  echo "$score"
}
SESSION_COMPLEXITY="$(_compute_complexity)"

# =============================================================================
# [maker] BANNER — Industrial ASCII, mechanical feel
# =============================================================================
print_banner() {
  printf '\n'
  if [ "$HAS_COLOR" = true ]; then
    local d=0.03
    printf '  %b     ___  ______ __  __ __   _  __ ___        _____ ____ ______%b\n' "$RED" "$NC";       sleep "$d"
    printf '  %b    /   |/_  __/ / / / /  / /_/ / /  /  / /   / ___/ /  _/_  __/%b\n' "$BR_RED" "$NC";   sleep "$d"
    printf '  %b   / /| | / / / / / / /  / __ / /__/ /_/ /   / / __/ /  / / /   %b\n' "$BR_RED" "$NC";    sleep "$d"
    printf '  %b  / ___ |/ / / /_/ / /__/ / / / ___/ __, /   / /_/ / /  / / /   %b\n' "$BR_YELLOW" "$NC"; sleep "$d"
    printf '  %b /_/  |_/_/  \____/____/_/ /_/_/  /_/  /_/    \____/_/  /_/ /_/  %b\n' "$WHITE" "$NC";    sleep "$d"
    printf '\n'
    printf '  %b' "$GRAY"
    local tag="ATULYA CORTEX FOR GIT MEMORY"
    local i
    for ((i = 0; i < ${#tag}; i++)); do
      printf '%s' "${tag:$i:1}"
      sleep 0.008
    done
    printf '%b  %bv%s%b\n' "$NC" "$BR_RED" "$ATULYA_VERSION" "$NC"
  else
    printf '  ATULYA-GIT v%s\n' "$ATULYA_VERSION"
    printf '  Cortex-grade git memory synthesis\n'
  fi
  printf '  %b@author: Anurag Atulya%b\n' "$GRAY" "$NC"
  printf '\n'
}

# =============================================================================
# [maker] PROJECT INTELLIGENCE PANEL — mechanical gauges
# =============================================================================
print_project_panel() {
  hr "CORTEX SCAN"
  printf '\n'

  local health_color health_label health_sym
  if [ "$COUNT_TOTAL_DIRTY" -eq 0 ]; then
    health_color="$GREEN"     health_label="CLEAN"    health_sym="[VALID]"
  elif [ "$COUNT_TOTAL_DIRTY" -le 5 ]; then
    health_color="$GREEN"     health_label="LIGHT"    health_sym="[--]"
  elif [ "$COUNT_TOTAL_DIRTY" -le 20 ]; then
    health_color="$BR_YELLOW" health_label="MODERATE" health_sym="[==]"
  else
    health_color="$RED"       health_label="HEAVY"    health_sym="[##]"
  fi

  printf '  %b%s%b %b%s%b  ~~>  %b%s%b  @  %b%s%b\n' \
    "$health_color" "$health_sym" "$NC" \
    "$WHITE$BOLD" "$PROJECT_NAME" "$NC" \
    "$BR_RED" "$CURRENT_BRANCH" "$NC" \
    "$GRAY" "${REMOTE_NAME:-local}" "$NC"
  printf '  %b%s commits  |  %s contributors  |  born %s  |  tag %s%b\n' \
    "$GRAY" "$TOTAL_COMMITS" "$CONTRIBUTORS" "$REPO_BORN" "$LAST_TAG" "$NC"
  printf '  %bHEAD%b  %b%s%b  %b%s%b\n' \
    "$GRAY" "$NC" "$BR_RED" "$HEAD_SHA" "$NC" "$GRAY" "$HEAD_MSG" "$NC"
  printf '\n'

  hr "LIVE SIGNALS"
  printf '\n'
  _gauge "Unstaged"  "$COUNT_UNSTAGED"  "$BR_YELLOW" 20
  _gauge "Staged"    "$COUNT_STAGED"    "$GREEN"     20
  _gauge "Untracked" "$COUNT_UNTRACKED" "$YELLOW"    20
  _gauge "Unpushed"  "$COUNT_UNPUSHED"  "$RED"       20
  printf '\n'

  # Complexity meter
  local cx_bar="" cx_filled=$((SESSION_COMPLEXITY * 30 / 100)) i
  for ((i = 0; i < 30; i++)); do
    if [ "$i" -lt "$cx_filled" ]; then cx_bar+="="; else cx_bar+="."; fi
  done
  local cx_color="$GREEN"
  if [ "$SESSION_COMPLEXITY" -gt 60 ]; then cx_color="$RED"
  elif [ "$SESSION_COMPLEXITY" -gt 30 ]; then cx_color="$BR_YELLOW"; fi
  printf '  %bActivation%b  %b[%s]%b  %b%s/100%b  %b%s%b\n' \
    "$GRAY" "$NC" "$cx_color" "$cx_bar" "$NC" \
    "$WHITE$BOLD" "$SESSION_COMPLEXITY" "$NC" \
    "$health_color" "$health_label" "$NC"
  printf '\n'
}

_gauge() {
  local label="$1" count="$2" color="$3" max="$4"
  local bar_w=24
  if [ "$count" = "N/A" ]; then
    printf '  %-11s %b|%b %b---%b\n' "$label" "$GRAY" "$NC" "$GRAY" "$NC"
    return
  fi
  local filled=0
  if [ "$count" -gt 0 ] 2>/dev/null; then
    filled=$((count > max ? bar_w : count * bar_w / max))
    if [ "$filled" -lt 1 ] && [ "$count" -gt 0 ]; then filled=1; fi
  fi
  local bar="" i
  for ((i = 0; i < bar_w; i++)); do
    if [ "$i" -lt "$filled" ]; then bar+="█"; else bar+="░"; fi
  done
  printf '  %-11s %b%s%b%b%s%b  %b%3s%b\n' \
    "$label" \
    "$color" "${bar:0:$filled}" "$NC" \
    "$GRAY" "${bar:$filled}" "$NC" \
    "$WHITE$BOLD" "$count" "$NC"
}

# =============================================================================
# [mover] INTERACTIVE SCOPE SELECTION — smart recommendations
# =============================================================================
select_scope_interactive() {
  hr "SELECT MEMORY WINDOW"
  printf '\n'

  local recommended="" rec_reason=""
  if [ "$COUNT_STAGED" -gt 0 ]; then
    recommended="2"; rec_reason="$COUNT_STAGED staged changes ready to document"
  elif [ "$COUNT_UNPUSHED" != "N/A" ] && [ "$COUNT_UNPUSHED" != "0" ]; then
    recommended="4"; rec_reason="$COUNT_UNPUSHED unpushed commits detected"
  elif [ "$COUNT_UNSTAGED" -gt 0 ]; then
    recommended="1"; rec_reason="$COUNT_UNSTAGED unstaged working tree changes"
  elif [ "$COUNT_UNTRACKED" -gt 0 ]; then
    recommended="3"; rec_reason="$COUNT_UNTRACKED new untracked files"
  fi

  if [ -n "$recommended" ]; then
    printf '  %b[~~>]%b %bRECOMMENDED:%b %s\n\n' "$BR_RED" "$NC" "$WHITE$BOLD" "$NC" "$rec_reason"
  fi

  _opt() {
    local n="$1" lbl="$2" meta="$3" is_rec="${4:-}"
    local marker=""
    if [ "$is_rec" = "1" ]; then marker=" ${GREEN}<~~${NC}"; fi
    printf '  %b%s%b  %-26s %b%s%b%b\n' "$WHITE$BOLD" "$n" "$NC" "$lbl" "$GRAY" "$meta" "$NC" "$marker"
  }

  _opt "1" "Unstaged changes"       "$COUNT_UNSTAGED files"         "$( [ "$recommended" = "1" ] && echo 1 )"
  _opt "2" "Staged changes"         "$COUNT_STAGED files"           "$( [ "$recommended" = "2" ] && echo 1 )"
  _opt "3" "All uncommitted"        "staged + unstaged + untracked" "$( [ "$recommended" = "3" ] && echo 1 )"
  _opt "4" "Unpushed commits"       "$COUNT_UNPUSHED commits"       "$( [ "$recommended" = "4" ] && echo 1 )"
  _opt "5" "Last commit"            "$HEAD_SHA"
  _opt "6" "Last N commits"         "specify N"
  _opt "7" "Since last tag"         "$LAST_TAG"
  _opt "8" "Custom range"           "FROM..TO"
  _opt "9" "Compare with branch"    "diff against branch"
  printf '  %b0%b  %bExit%b\n' "$WHITE$BOLD" "$NC" "$GRAY" "$NC"
  printf '\n'

  local choice
  while true; do
    if [ -n "$recommended" ]; then
      printf '  %b~~>%b Choice %b[%s]%b: ' "$BR_RED" "$NC" "$GRAY" "$recommended" "$NC"
    else
      printf '  %b~~>%b Choice: ' "$BR_RED" "$NC"
    fi
    read -r choice
    [ -z "$choice" ] && [ -n "$recommended" ] && choice="$recommended"

    case "$choice" in
      1)
        [ "$COUNT_UNSTAGED" -eq 0 ] && { log_warn "No unstaged changes."; continue; }
        SCOPE="unstaged"; break ;;
      2)
        [ "$COUNT_STAGED" -eq 0 ] && { log_warn "No staged changes."; continue; }
        SCOPE="staged"; break ;;
      3) SCOPE="all-uncommitted"; break ;;
      4)
        ([ "$COUNT_UNPUSHED" = "N/A" ] || [ "$COUNT_UNPUSHED" = "0" ]) && { log_warn "No unpushed commits."; continue; }
        SCOPE="unpushed"; break ;;
      5) SCOPE="last-commit"; break ;;
      6)
        printf '  %b--->%b How many? ' "$BR_RED" "$NC"
        read -r n_commits
        [[ "$n_commits" =~ ^[0-9]+$ ]] && [ "$n_commits" -gt 0 ] && { SCOPE="last-n"; GIT_RANGE="$n_commits"; break; }
        log_warn "Positive integer required." ;;
      7)
        [ "$LAST_TAG" = "none" ] && { log_warn "No tags found."; continue; }
        SCOPE="since-tag"; break ;;
      8)
        printf '  %b--->%b Range (e.g. abc..def): ' "$BR_RED" "$NC"
        read -r GIT_RANGE
        [ -n "$GIT_RANGE" ] && { SCOPE="range"; break; }
        log_warn "Range cannot be empty." ;;
      9)
        printf '  %b--->%b Branches:\n' "$BR_RED" "$NC"
        git branch --all --format='       %(refname:short)' | head -20
        printf '\n  %b--->%b Compare against: ' "$BR_RED" "$NC"
        read -r compare_branch
        git rev-parse "$compare_branch" >/dev/null 2>&1 && { SCOPE="range"; GIT_RANGE="${compare_branch}..HEAD"; break; }
        log_warn "Branch not found." ;;
      0) printf '\n'; typewriter "~~~~ nevermind" "$GRAY" 0.03; exit 0 ;;
      *) log_warn "Pick 0-9." ;;
    esac
  done
  printf '\n'
  log_ok "Memory window locked ~~> $(scope_label)"
}

# =============================================================================
# [shaker] OUTPUT CONFIGURATION
# =============================================================================
configure_output_interactive() {
  hr "MEMORY ARTIFACT CONFIG"
  printf '\n'

  printf '  %b---?%b Include inline diffs?   %b[Y/n]%b ' "$BR_RED" "$NC" "$GRAY" "$NC"
  read -r yn_diff
  case "$yn_diff" in [nN]*) INCLUDE_DIFF=false ;; esac

  printf '  %b---?%b Include file stats?     %b[Y/n]%b ' "$BR_RED" "$NC" "$GRAY" "$NC"
  read -r yn_stats
  case "$yn_stats" in [nN]*) INCLUDE_STATS=false ;; esac

  printf '  %b---?%b Output directory        %b[%s]%b ' "$BR_RED" "$NC" "$GRAY" "${OUTPUT_DIR:-$PROJECT_ROOT}" "$NC"
  read -r custom_dir
  [ -n "$custom_dir" ] && OUTPUT_DIR="$custom_dir"

  local default_fn="CHANGELOG-session-$(date +%Y%m%d-%H%M%S).md"
  printf '  %b---?%b Filename               %b[%s]%b ' "$BR_RED" "$NC" "$GRAY" "${OUTPUT_FILENAME:-$default_fn}" "$NC"
  read -r custom_fn
  [ -n "$custom_fn" ] && OUTPUT_FILENAME="$custom_fn"
  printf '\n'
}

# =============================================================================
# [root] GIT DATA ENGINE — DRY scope dispatcher
# =============================================================================
_scope_diff_args() {
  case "$SCOPE" in
    unstaged)        echo "" ;;
    staged)          echo "--cached" ;;
    all-uncommitted) echo "HEAD" ;;
    unpushed)        echo "${UPSTREAM}..HEAD" ;;
    last-commit)
      if [ "$HAS_HEAD_PARENT" = true ]; then
        echo "HEAD~1..HEAD"
      else
        echo "${EMPTY_TREE_SHA}..HEAD"
      fi
      ;;
    last-n)          _scope_last_n_range ;;
    since-tag)       echo "${LAST_TAG}..HEAD" ;;
    range)           echo "$GIT_RANGE" ;;
  esac
}

_scope_last_n_range() {
  local requested="${GIT_RANGE:-1}"
  local oldest_commit start_ref

  oldest_commit="$(git rev-list --max-count="$requested" --reverse HEAD 2>/dev/null | head -1 || true)"
  if [ -z "$oldest_commit" ]; then
    echo "${EMPTY_TREE_SHA}..HEAD"
    return
  fi

  start_ref="$(git rev-parse "${oldest_commit}^" 2>/dev/null || echo "${EMPTY_TREE_SHA}")"
  echo "${start_ref}..HEAD"
}

get_diff_content() {
  local args
  args="$(_scope_diff_args)"
  # shellcheck disable=SC2086
  git diff $args 2>/dev/null || true

  if [ "$SCOPE" = "all-uncommitted" ]; then
    local untracked max_lines=80
    untracked="$(git ls-files --others --exclude-standard | grep -v '^CHANGELOG-session-' || true)"
    if [ -n "$untracked" ]; then
      printf '\n# Untracked files (new, not yet added):\n'
      echo "$untracked" | while IFS= read -r f; do
        printf '\n--- /dev/null\n+++ b/%s\n' "$f"
        if [ -f "$f" ] && LC_ALL=C grep -Iq . "$f" 2>/dev/null; then
          local total
          total="$(wc -l < "$f" | tr -d ' ')"
          if [ "$total" -le "$max_lines" ]; then
            sed 's/^/+/' "$f" 2>/dev/null || true
          else
            head -n "$max_lines" "$f" | sed 's/^/+/' 2>/dev/null || true
            printf '+\n+... [truncated — %s lines total, first %s shown]\n' "$total" "$max_lines"
          fi
        else
          printf '+[binary file]\n'
        fi
      done
    fi
  fi
}

get_stat_content() {
  local args
  args="$(_scope_diff_args)"
  # shellcheck disable=SC2086
  git diff --stat $args 2>/dev/null || true
}

get_changed_file_list() {
  local args
  args="$(_scope_diff_args)"
  # shellcheck disable=SC2086
  git diff --name-status $args 2>/dev/null || true
  if [ "$SCOPE" = "all-uncommitted" ]; then
    git ls-files --others --exclude-standard | grep -v '^CHANGELOG-session-' | sed 's/^/?\t/' || true
  fi
}

get_commit_log_raw() {
  local fmt="$1"
  case "$SCOPE" in
    unpushed)    git log "$UPSTREAM"..HEAD --format="$fmt" 2>/dev/null ;;
    last-commit) git log -1 --format="$fmt" 2>/dev/null ;;
    last-n)      git log -"${GIT_RANGE}" --format="$fmt" 2>/dev/null ;;
    since-tag)   git log "${LAST_TAG}"..HEAD --format="$fmt" 2>/dev/null ;;
    range)       git log "$GIT_RANGE" --format="$fmt" 2>/dev/null ;;
    *)           return 1 ;;
  esac
}

scope_label() {
  case "$SCOPE" in
    unstaged)        echo "Unstaged working tree changes" ;;
    staged)          echo "Staged changes (ready to commit)" ;;
    all-uncommitted) echo "All uncommitted (staged + unstaged + untracked)" ;;
    unpushed)        echo "Unpushed commits (${UPSTREAM}..HEAD)" ;;
    last-commit)
      if [ "$HAS_HEAD_PARENT" = true ]; then
        echo "Last commit (HEAD~1..HEAD)"
      else
        echo "Last commit (root commit)"
      fi
      ;;
    last-n)          echo "Last $GIT_RANGE commits" ;;
    since-tag)       echo "Since tag $LAST_TAG" ;;
    range)           echo "Range: $GIT_RANGE" ;;
  esac
}

# =============================================================================
# [breaker] CHANGE CLASSIFICATION ENGINE
# Semantic categorization by file purpose, not just directory
# =============================================================================
classify_change() {
  local filepath="$1" status="$2"
  local status_label
  case "$status" in
    M)  status_label="Modified" ;;
    A)  status_label="Added" ;;
    D)  status_label="Deleted" ;;
    R*) status_label="Renamed" ;;
    ?)  status_label="New" ;;
    *)  status_label="$status" ;;
  esac

  local category
  case "$filepath" in
    *.test.*|*_test.*|*/test_*|*/tests/*) category="tests" ;;
    *alembic*|*migration*)                category="database" ;;
    *.md|*.rst|docs/*|*-docs/*)           category="docs" ;;
    *.yml|*.yaml|*.toml|*.cfg|*.ini)      category="config" ;;
    *.env*)                               category="config" ;;
    *Dockerfile*|docker/*)                category="infra" ;;
    *.sh|scripts/*|Makefile)              category="tooling" ;;
    *.ts|*.tsx|*.jsx|*.css|*.scss|*.html) category="frontend" ;;
    *.py)                                 category="backend" ;;
    *.rs)                                 category="native" ;;
    *.go)                                 category="backend" ;;
    *.sql)                                category="database" ;;
    *lock*|*-lock.*)                      category="deps" ;;
    *.json)                               category="config" ;;
    *)                                    category="other" ;;
  esac

  echo "${category}|${status_label}|${filepath}"
}

_cat_label() {
  case "$1" in
    backend)  echo "Backend" ;;
    frontend) echo "Frontend" ;;
    tests)    echo "Tests" ;;
    database) echo "Database & Migrations" ;;
    config)   echo "Configuration" ;;
    infra)    echo "Infrastructure" ;;
    tooling)  echo "Tooling & Scripts" ;;
    docs)     echo "Documentation" ;;
    native)   echo "Native (Rust)" ;;
    deps)     echo "Dependencies" ;;
    other)    echo "Other" ;;
  esac
}

_cat_icon() {
  case "$1" in
    backend)  echo ":gear:" ;;
    frontend) echo ":art:" ;;
    tests)    echo ":test_tube:" ;;
    database) echo ":floppy_disk:" ;;
    config)   echo ":wrench:" ;;
    infra)    echo ":whale:" ;;
    tooling)  echo ":hammer:" ;;
    docs)     echo ":book:" ;;
    native)   echo ":crab:" ;;
    deps)     echo ":link:" ;;
    other)    echo ":file_folder:" ;;
  esac
}

# =============================================================================
# [maker] PER-FILE DIFF EMITTER — collapsible, with add/del counts
# =============================================================================
emit_per_file_diffs() {
  local diff_output
  diff_output="$(get_diff_content 2>/dev/null || true)"

  if [ -z "$diff_output" ]; then
    printf '%s\n' "_No diff available._"
    return
  fi

  local current_file="" current_block="" file_count=0

  while IFS= read -r line; do
    if [[ "$line" == "diff --git"* ]]; then
      if [ -n "$current_file" ] && [ -n "$current_block" ]; then
        _emit_diff_block "$current_file" "$current_block"
        file_count=$((file_count + 1))
      fi
      current_file="$(echo "$line" | sed 's|^diff --git a/.* b/||')"
      current_block="$line"
    elif [[ "$line" == "--- /dev/null" ]] && [ -z "$current_file" ]; then
      if [ -n "$current_file" ] && [ -n "$current_block" ]; then
        _emit_diff_block "$current_file" "$current_block"
        file_count=$((file_count + 1))
      fi
      current_block="$line"
      current_file=""
    elif [[ "$line" == "+++ b/"* ]] && [ -z "$current_file" ]; then
      current_file="${line#+++ b/}"
      current_block="${current_block}"$'\n'"${line}"
    elif [[ "$line" == "# Untracked files"* ]]; then
      if [ -n "$current_file" ] && [ -n "$current_block" ]; then
        _emit_diff_block "$current_file" "$current_block"
        file_count=$((file_count + 1))
      fi
      current_file="" current_block=""
      printf '\n#### Untracked Files\n\n'
    else
      current_block="${current_block}"$'\n'"${line}"
    fi
  done <<< "$diff_output"

  if [ -n "$current_file" ] && [ -n "$current_block" ]; then
    _emit_diff_block "$current_file" "$current_block"
    file_count=$((file_count + 1))
  fi

  [ "$file_count" -eq 0 ] && printf '%s\n' "_No diff available._"
}

_emit_diff_block() {
  local filename="$1" block="$2"
  local lc adds dels
  lc="$(echo "$block" | wc -l | tr -d ' ')"
  adds="$(printf '%s\n' "$block" | awk '/^\+[^+]/ {count++} END {print count + 0}')"
  dels="$(printf '%s\n' "$block" | awk '/^\-[^-]/ {count++} END {print count + 0}')"

  printf '<details>\n'
  printf '<summary><code>%s</code> &nbsp; <sub>+%s -%s | %s lines</sub></summary>\n\n' \
    "$filename" "$adds" "$dels" "$lc"
  printf '```diff\n'
  printf '%s\n' "$block"
  printf '```\n\n'
  printf '</details>\n\n'
}

# =============================================================================
# [root] COMPONENT BREAKDOWN (awk — directory-level grouping)
# =============================================================================
get_component_breakdown() {
  get_changed_file_list | awk -F'\t' '{
    split($NF, parts, "/")
    component = parts[1]
    status = $1
    if (status == "M") type = "modified"
    else if (status == "A" || status == "?") type = "added"
    else if (status == "D") type = "deleted"
    else if (substr(status, 1, 1) == "R") type = "renamed"
    else type = status
    components[component]++
    types[component ":::" type]++
  }
  END {
    for (c in components) {
      detail = ""
      for (k in types) {
        n = split(k, kparts, ":::")
        if (kparts[1] == c) {
          if (detail != "") detail = detail ", "
          detail = detail types[k] " " kparts[2]
        }
      }
      printf "| `%s` | %d | %s |\n", c, components[c], detail
    }
  }' | sort
}

# =============================================================================
# [maker] MARKDOWN ASSEMBLY — Industrial-grade, semantic, production-ready
# =============================================================================
generate_changelog() {
  local outdir="${OUTPUT_DIR:-$PROJECT_ROOT}"
  local outfile="${OUTPUT_FILENAME:-CHANGELOG-session-$(date +%Y%m%d-%H%M%S).md}"
  local outpath="$outdir/$outfile"
  mkdir -p "$outdir"

  printf '\n'
  hr "MEMORY SYNTHESIS"
  printf '\n'

  # -- Step 1: Analyze --
  spinner_start "Reading repository memory state..."
  GEN_TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  local diffstat_line
  diffstat_line="$(get_stat_content 2>/dev/null | tail -1 || echo '')"
  GEN_INSERTIONS="$(echo "$diffstat_line" | grep -oE '[0-9]+ insertion' | grep -oE '[0-9]+' || echo '0')"
  GEN_DELETIONS="$(echo "$diffstat_line" | grep -oE '[0-9]+ deletion' | grep -oE '[0-9]+' || echo '0')"
  GEN_FILES_CHANGED="$(get_changed_file_list 2>/dev/null | wc -l | tr -d ' ')"
  sleep 0.3
  spinner_stop "$GEN_FILES_CHANGED signals | +$GEN_INSERTIONS -$GEN_DELETIONS"

  # -- Step 2: Classify --
  spinner_start "Clustering code signals..."
  GEN_CLASSIFIED=""
  while IFS=$'\t' read -r status filepath; do
    [ -z "$filepath" ] && continue
    GEN_CLASSIFIED+="$(classify_change "$filepath" "$status")"$'\n'
  done < <(get_changed_file_list 2>/dev/null)
  GEN_CATEGORIES=""
  [ -n "$GEN_CLASSIFIED" ] && GEN_CATEGORIES="$(echo "$GEN_CLASSIFIED" | awk -F'|' 'NF{print $1}' | sort | uniq -c | sort -rn)"
  local cat_count
  cat_count="$(echo "$GEN_CATEGORIES" | grep -c '[a-z]' || echo '0')"
  sleep 0.2
  spinner_stop "$cat_count signal clusters detected"

  # -- Step 3: Impact Assessment --
  spinner_start "Estimating cognitive weight..."
  local total_delta=$((GEN_INSERTIONS + GEN_DELETIONS))
  if [ "$total_delta" -le 10 ]; then
    GEN_IMPACT="Minimal" GEN_IMPACT_DESC="Cosmetic or config tweak"
  elif [ "$total_delta" -le 50 ]; then
    GEN_IMPACT="Low" GEN_IMPACT_DESC="Targeted fix or small feature"
  elif [ "$total_delta" -le 200 ]; then
    GEN_IMPACT="Moderate" GEN_IMPACT_DESC="Feature work or significant refactor"
  elif [ "$total_delta" -le 1000 ]; then
    GEN_IMPACT="High" GEN_IMPACT_DESC="Major feature or architecture change"
  else
    GEN_IMPACT="Critical" GEN_IMPACT_DESC="Large-scale rewrite or migration"
  fi

  if [ "$GEN_INSERTIONS" -gt "$GEN_DELETIONS" ]; then
    local ratio=0
    [ "$GEN_DELETIONS" -gt 0 ] && ratio=$((GEN_INSERTIONS / GEN_DELETIONS))
    if [ "$ratio" -gt 5 ]; then GEN_DIRECTION="Primarily additive (new code)"
    else GEN_DIRECTION="Net growth with refactoring"; fi
  elif [ "$GEN_DELETIONS" -gt "$GEN_INSERTIONS" ]; then
    GEN_DIRECTION="Net reduction (cleanup / removal)"
  else
    GEN_DIRECTION="Balanced (refactor / rewrite)"
  fi
  sleep 0.1
  spinner_stop "Weight: $GEN_IMPACT | $GEN_DIRECTION"

  # -- Step 4: Compose --
  spinner_start "Writing memory artifact..."
  sleep 0.2
  spinner_stop "Memory artifact assembled"

  # -- Step 5: Write file (subshell — pipefail-safe) --
  _write_changelog_file "$outpath"

  log_ok "Written ~~> $(basename "$outpath")"

  # -- Result Panel --
  printf '\n'
  hr "ARTIFACT READY"
  printf '\n'
  printf '  %bFile%b       %s\n'       "$GRAY" "$NC" "$outpath"
  printf '  %bWindow%b     %s\n'       "$GRAY" "$NC" "$(scope_label)"
  printf '  %bWeight%b     %b%s%b — %s\n' "$GRAY" "$NC" "$WHITE$BOLD" "$GEN_IMPACT" "$NC" "$GEN_IMPACT_DESC"
  printf '  %bVector%b     %s\n'       "$GRAY" "$NC" "$GEN_DIRECTION"
  printf '  %bFiles%b      %s changed\n' "$GRAY" "$NC" "$GEN_FILES_CHANGED"
  printf '  %bDelta%b      %b+%s%b  %b-%s%b\n' "$GRAY" "$NC" "$GREEN" "$GEN_INSERTIONS" "$NC" "$RED" "$GEN_DELETIONS" "$NC"
  printf '  %bSize%b       %s bytes\n'  "$GRAY" "$NC" "$(wc -c < "$outpath" | tr -d ' ')"

  if [ -n "$GEN_CATEGORIES" ]; then
    local cat_str=""
    while read -r count cat_name || [ -n "$cat_name" ]; do
      [ -z "$cat_name" ] && continue
      cat_str+="$(_cat_label "$cat_name")($count) "
    done <<< "$GEN_CATEGORIES"
    printf '  %bClusters%b   %s\n' "$GRAY" "$NC" "$cat_str"
  fi
  printf '\n'

  if [ "$INTERACTIVE" = true ]; then
    post_generation_menu "$outpath"
  fi
}

validate_scope_config() {
  case "$SCOPE" in
    unstaged|staged|all-uncommitted|unpushed|last-commit|last-n|since-tag|range) ;;
    *) die "Invalid scope: $SCOPE" 10 ;;
  esac

  if [ "$SCOPE" = "range" ] && [ -z "$GIT_RANGE" ]; then
    die "--range required with scope=range" 10
  fi

  if [ "$SCOPE" = "last-n" ]; then
    [[ "$GIT_RANGE" =~ ^[0-9]+$ ]] || die "--range must be a positive integer for scope=last-n" 10
    if [ "$GIT_RANGE" -lt 1 ]; then
      die "--range must be >= 1 for scope=last-n" 10
    fi
    if [ "$GIT_RANGE" -gt "$TOTAL_COMMITS" ]; then
      log_warn "Requested $GIT_RANGE commits, but repo has $TOTAL_COMMITS. Clamping to $TOTAL_COMMITS."
      GIT_RANGE="$TOTAL_COMMITS"
    fi
  fi

  if [ "$SCOPE" = "since-tag" ] && [ "$LAST_TAG" = "none" ]; then
    die "No tags found for scope=since-tag" 10
  fi

  if [ "$SCOPE" = "unpushed" ] && ([ "$COUNT_UNPUSHED" = "N/A" ] || [ "$COUNT_UNPUSHED" = "0" ]); then
    die "No unpushed commits." 10
  fi

  if [ "$SCOPE" = "range" ] && ! git rev-list --max-count=1 "$GIT_RANGE" >/dev/null 2>&1; then
    die "Invalid git range: $GIT_RANGE" 10
  fi
}

# Isolated file writer — subshell with set +e to tolerate pipe returns
_write_changelog_file() {
  local outpath="$1"
  (
    set +e

    cat <<MD_HEADER
<!-- 8888888888~~~~888888888 -->
<!-- Auto-generated by atulya-git v${ATULYA_VERSION} -->
<!-- @author: Anurag Atulya  -->
<!-- Atulya Cortex Memory Artifact -->

# Cortex Session Memory

> **$(scope_label)**
> Generated: \`${GEN_TIMESTAMP}\` | Branch: \`${CURRENT_BRANCH}\` | Project: \`${PROJECT_NAME}\`

---

## Cognitive Summary

| | |
|:---|:---|
| **Project** | \`${PROJECT_NAME}\` |
| **Branch** | \`${CURRENT_BRANCH}\` on \`${REMOTE_NAME:-local}\` |
| **HEAD** | [\`${HEAD_SHA}\`](../../commit/${FULL_SHA}) — ${HEAD_MSG} |
| **Last Tag** | \`${LAST_TAG}\` |
| **Memory Window** | $(scope_label) |
| **Cognitive Weight** | **${GEN_IMPACT}** — ${GEN_IMPACT_DESC} |
| **Drift Vector** | ${GEN_DIRECTION} |
| **Delta** | \`${GEN_FILES_CHANGED}\` files | \`+${GEN_INSERTIONS}\` | \`-${GEN_DELETIONS}\` |
| **Activation** | ${SESSION_COMPLEXITY}/100 |

MD_HEADER

    cat <<BRAIN_NOTE
> This artifact is a living memory surface for Atulya development.
> Its structure is intentionally extensible and will grow as the cortex gains new workflows, signals, and intelligence.

BRAIN_NOTE

    # Commits
    local commit_log
    commit_log="$(get_commit_log_raw '- [`%h`] %s — _%an_ (%ar)' 2>/dev/null)" || true
    if [ -n "$commit_log" ]; then
      printf '%s\n\n%s\n\n%s\n\n' "---" "## Memory Trail" "$commit_log"
    fi

    # Semantic categories
    printf '%s\n\n%s\n\n' "---" "## Signal Clusters"
    if [ -n "$GEN_CATEGORIES" ]; then
      echo "$GEN_CATEGORIES" | while read -r count cat_name; do
        [ -z "$cat_name" ] && continue
        printf '### %s %s (%s files)\n\n' "$(_cat_icon "$cat_name")" "$(_cat_label "$cat_name")" "$count"
        printf '| Status | File |\n'
        printf '|:------:|------|\n'
        echo "$GEN_CLASSIFIED" | grep "^${cat_name}|" | while IFS='|' read -r _ st fp; do
          [ -z "$fp" ] && continue
          printf '| %s | `%s` |\n' "$st" "$fp"
        done
        printf '\n'
      done
    else
      printf '%s\n\n' "_No categorized changes._"
    fi

    # Components
    cat <<COMP
---

## Cortex Surfaces Touched

| Component | Files | Breakdown |
|:----------|:-----:|:----------|
$(get_component_breakdown 2>/dev/null || echo '| _none_ | 0 | — |')

COMP

    # Stats
    if [ "$INCLUDE_STATS" = true ]; then
      printf '%s\n\n%s\n\n' "---" "## Structural Statistics"
      printf '```\n'
      get_stat_content 2>/dev/null || echo 'No stats available.'
      printf '```\n\n'
    fi

    # Diffs
    if [ "$INCLUDE_DIFF" = true ]; then
      printf '%s\n\n%s\n\n' "---" "## Synaptic Diffs"
      printf '%s\n\n' "_Click any file to expand its diff._"
      emit_per_file_diffs
    fi

    # Footer
    cat <<FOOTER
---

<sub>
Generated \`${GEN_TIMESTAMP}\` | Window: <strong>${SCOPE}</strong> | Branch: \`${CURRENT_BRANCH}\` | \`${PROJECT_NAME}\`
<br>atulya-git v${ATULYA_VERSION} | Atulya cortex memory artifact | 8888888888~~~~888888888
</sub>
FOOTER

  ) > "$outpath"
}

# =============================================================================
# [mover] POST-GENERATION ACTIONS
# =============================================================================
post_generation_menu() {
  local filepath="$1"

  hr "NEXT SYNAPSES"
  printf '\n'
  printf '  %b1%b  Open in editor        %b5%b  Stage this file\n'       "$WHITE$BOLD" "$NC" "$WHITE$BOLD" "$NC"
  printf '  %b2%b  Print to stdout       %b6%b  Copy content to clipboard\n' "$WHITE$BOLD" "$NC" "$WHITE$BOLD" "$NC"
  printf '  %b3%b  Copy path             %b7%b  Generate another scope\n'   "$WHITE$BOLD" "$NC" "$WHITE$BOLD" "$NC"
  printf '  %b4%b  Preview (first 60L)   %b0%b  Done\n'                    "$WHITE$BOLD" "$NC" "$WHITE$BOLD" "$NC"
  printf '\n'

  while true; do
    printf '  %b~~>%b ' "$BR_RED" "$NC"
    read -r action
    case "$action" in
      1)
        local ed="${EDITOR:-code}"
        command -v "$ed" >/dev/null 2>&1 && { "$ed" "$filepath"; log_ok "Opened in $ed"; } || log_warn "$ed not found."
        ;;
      2) printf '\n'; cat "$filepath"; printf '\n' ;;
      3)
        if command -v pbcopy >/dev/null 2>&1; then echo "$filepath" | pbcopy; log_ok "Path copied [yayyy]"
        elif command -v xclip >/dev/null 2>&1; then echo "$filepath" | xclip -selection clipboard; log_ok "Path copied [yayyy]"
        else printf '  %s\n' "$filepath"; fi
        ;;
      4) printf '\n'; head -60 "$filepath"; printf '\n  %b... (60 lines shown)%b\n\n' "$GRAY" "$NC" ;;
      5) git add "$filepath"; log_ok "Staged: $(basename "$filepath")" ;;
      6)
        if command -v pbcopy >/dev/null 2>&1; then cat "$filepath" | pbcopy; log_ok "Content copied [yayyy]"
        elif command -v xclip >/dev/null 2>&1; then cat "$filepath" | xclip -selection clipboard; log_ok "Content copied [yayyy]"
        else log_warn "No clipboard tool."; fi
        ;;
      7) log_info "Restarting..."; select_scope_interactive; generate_changelog; return ;;
      0|"")
        printf '\n'
        hr
        typewriter "[success] Cortex memory artifact complete. 8888888888~~~~888888888" "$GREEN" 0.012
        printf '\n'
        exit 0
        ;;
      *) log_warn "Pick 0-7." ;;
    esac
  done
}

# =============================================================================
# [root] MAIN ORCHESTRATOR
# =============================================================================
main() {
  print_banner

  spinner_start "Scanning cortex workspace..."
  sleep 0.35
  spinner_stop "Detected: $PROJECT_NAME @ $CURRENT_BRANCH ($HEAD_SHA)"

  print_project_panel

  if [ -n "$SCOPE" ]; then
    validate_scope_config
    log_ok "Memory window ~~> $(scope_label)"
    printf '\n'
  else
    [ "$INTERACTIVE" = false ] && die "--scope required in non-interactive mode" 10
    select_scope_interactive
  fi

  if [ "$INTERACTIVE" = true ] && [ -z "$OUTPUT_FILENAME" ]; then
    configure_output_interactive
  fi

  generate_changelog
}

main
