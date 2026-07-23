#!/bin/sh
set -eu

# Small interactive front door for the canonical atulya-admin CLI.
# The CLI remains responsible for validation, secrets, confirmations, and
# database work; this script only collects the few arguments needed to start a
# command and keeps the operator in one predictable flow.

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ROOT_DIR="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
API_DIR="$ROOT_DIR/atulya-api"
UV="${UV:-uv}"

if ! command -v "$UV" >/dev/null 2>&1; then
	printf '%s\n' "Missing required command: $UV" >&2
	exit 1
fi

run_admin() {
	(
		cd "$API_DIR"
		"$UV" run atulya-admin "$@"
	)
}

pause() {
	printf '\n%s' 'Press Enter to return to the admin menu...'
	IFS= read -r _ || true
}

run_and_report() {
	if run_admin "$@"; then
		printf '\n%s\n' 'Command completed.'
	else
		status=$?
		printf '\n%s\n' "Command failed with exit code $status. Review the message above."
	fi
	pause
}

prompt_or_default() {
	prompt="$1"
	default="$2"
	printf '%s' "$prompt"
	IFS= read -r value || exit 0
	if [ -n "$value" ]; then
		printf '%s' "$value"
	else
		printf '%s' "$default"
	fi
}

generate_auth_env() {
	environment="$(prompt_or_default 'Environment [development/staging/production] (development): ' 'development')"
	case "$environment" in
		development|staging|production) run_and_report generate-auth-env --environment "$environment" ;;
		*) printf '%s\n' 'Choose development, staging, or production.'; pause ;;
	esac
}

create_platform_admin() {
	# Email, name, and hidden password prompts stay inside the Python CLI.
	run_and_report create-platform-admin
}

revoke_platform_admin() {
	email="$(prompt_or_default 'Platform admin email: ' '')"
	[ -n "$email" ] || { printf '%s\n' 'Email is required.'; pause; return; }
	run_and_report revoke-platform-admin --email "$email"
}

run_migration() {
	schema="$(prompt_or_default 'Schema (public): ' 'public')"
	run_and_report run-db-migration --schema "$schema"
}

backup_database() {
	default_output="backups/atulya-$(date '+%Y%m%d-%H%M%S').zip"
	output="$(prompt_or_default "Output file ($default_output): " "$default_output")"
	schema="$(prompt_or_default 'Schema (public): ' 'public')"
	run_and_report backup "$output" --schema "$schema"
}

restore_database() {
	input_file="$(prompt_or_default 'Backup zip path: ' '')"
	[ -n "$input_file" ] || { printf '%s\n' 'Backup path is required.'; pause; return; }
	schema="$(prompt_or_default 'Schema (public): ' 'public')"
	# The CLI always keeps its destructive restore confirmation unless the
	# operator explicitly chooses the non-interactive --yes form.
	run_and_report restore "$input_file" --schema "$schema"
}

decommission_worker() {
	worker_id="$(prompt_or_default 'Worker ID: ' '')"
	[ -n "$worker_id" ] || { printf '%s\n' 'Worker ID is required.'; pause; return; }
	schema="$(prompt_or_default 'Schema (public): ' 'public')"
	run_and_report decommission-worker "$worker_id" --schema "$schema"
}

backfill_timeline() {
	schema="$(prompt_or_default 'Schema (public): ' 'public')"
	bank_id="$(prompt_or_default 'Bank ID (leave blank for all banks): ' '')"
	if [ -n "$bank_id" ]; then
		run_and_report backfill-timeline-metadata --schema "$schema" --bank-id "$bank_id" --dry-run
	else
		run_and_report backfill-timeline-metadata --schema "$schema" --dry-run
	fi
}

run_forge() {
	bank_id="$(prompt_or_default 'Bank ID: ' '')"
	[ -n "$bank_id" ] || { printf '%s\n' 'Bank ID is required.'; pause; return; }
	recipe="$(prompt_or_default 'Recipe (consolidation_pairs): ' 'consolidation_pairs')"
	run_and_report forge run --bank "$bank_id" --recipe "$recipe"
}

reset_development() {
	printf '%s\n' 'WARNING: this destroys development auth, organization schemas, and bank data.'
	printf '%s' 'Type RESET-ATULYA-AUTH-AND-BANKS to continue: '
	IFS= read -r confirmation || exit 0
	if [ "$confirmation" = 'RESET-ATULYA-AUTH-AND-BANKS' ]; then
		run_and_report reset-development-auth-and-banks --confirm "$confirmation"
	else
		printf '%s\n' 'Reset cancelled; confirmation did not match.'
		pause
	fi
}

while :; do
	printf '\n%s\n' 'Atulya admin'
	printf '%s\n' '----------------------------------------'
	printf '%s\n' '  1) Generate auth environment values'
	printf '%s\n' '  2) Create platform admin'
	printf '%s\n' '  3) List platform admins'
	printf '%s\n' '  4) Revoke platform admin access'
	printf '%s\n' '  5) Run database migrations'
	printf '%s\n' '  6) Backup database'
	printf '%s\n' '  7) Restore database'
	printf '%s\n' '  8) Decommission a worker'
	printf '%s\n' '  9) Backfill timeline metadata (dry run)'
	printf '%s\n' ' 10) Run Data Forge job'
	printf '%s\n' ' 11) Reset development auth and banks'
	printf '%s\n' '  h) Show complete CLI help'
	printf '%s\n' '  q) Quit'
	printf '%s' 'Select an operation: '

	IFS= read -r choice || exit 0
	case "$choice" in
		1) generate_auth_env ;;
		2) create_platform_admin ;;
		3) run_and_report list-platform-admins ;;
		4) revoke_platform_admin ;;
		5) run_migration ;;
		6) backup_database ;;
		7) restore_database ;;
		8) decommission_worker ;;
		9) backfill_timeline ;;
		10) run_forge ;;
		11) reset_development ;;
		h|H) run_and_report --help ;;
		q|Q) printf '%s\n' 'Goodbye.'; exit 0 ;;
		*) printf '%s\n' 'Choose one of the listed options.'; pause ;;
	esac
done
