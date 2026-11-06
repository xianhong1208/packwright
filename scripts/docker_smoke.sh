#!/usr/bin/env bash
# End-to-end check of the Docker image: start it, build a real program twice
# through the API, then recreate the container on the same volume and check
# nothing was lost. Run from the repository root:
#
#   bash scripts/docker_smoke.sh            # builds packwright:smoke first
#   IMAGE=packwright:local SKIP_BUILD=1 bash scripts/docker_smoke.sh
set -euo pipefail

IMAGE="${IMAGE:-packwright:smoke}"
NAME=packwright-smoke
VOLUME=packwright-smoke-data
PORT="${SMOKE_PORT:-5918}"
BASE="http://127.0.0.1:$PORT"
PASSWORD="smoke-$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n')"
WORK="$(mktemp -d)"

cleanup() {
    status=$?
    if [ $status -ne 0 ]; then
        echo "---- container log (last 200 lines) ----"
        docker logs --tail 200 "$NAME" 2>&1 || true
    fi
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    docker volume rm "$VOLUME" >/dev/null 2>&1 || true
    rm -rf "$WORK"
    exit $status
}
trap cleanup EXIT

json() { python3 -c "import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1], {}, {'d': d}))" "$1"; }

if [ "${SKIP_BUILD:-0}" != "1" ]; then
    docker build -t "$IMAGE" .
fi

# A small program with one stdlib-heavy import, so there are C files to cache.
mkdir -p "$WORK/projects/hello"
cat > "$WORK/projects/hello/main.py" <<'PY'
import json


def main() -> None:
    print(json.dumps({"hello": "packwright"}))


if __name__ == "__main__":
    main()
PY
printf '[project]\nname = "hello"\nversion = "0.1.0"\nrequires-python = ">=3.13"\ndependencies = []\n' \
    > "$WORK/projects/hello/pyproject.toml"
chmod -R a+rwX "$WORK/projects"   # the container runs as uid 1000

start() {
    docker run -d --name "$NAME" -p "127.0.0.1:$PORT:5018" \
        -v "$VOLUME:/data" -v "$WORK/projects:/srv/projects" \
        -e BOOTSTRAP_ADMIN_PASSWORD="$PASSWORD" -e LOCAL_SOURCE_ROOTS=/srv/projects \
        "$IMAGE" >/dev/null
    for _ in $(seq 1 90); do
        if curl -fsS "$BASE/health" >/dev/null 2>&1; then return 0; fi
        sleep 1
    done
    echo "service did not become healthy" >&2
    return 1
}

start
echo "ok: service is up ($(curl -fsS "$BASE/health" | json "d.get('version')"))"

TOKEN=$(curl -fsS -X POST "$BASE/auth/login" -H 'Content-Type: application/json' \
    -d "{\"username\":\"admin\",\"password\":\"$PASSWORD\"}" | json "d['access_token']")
AUTH=(-H "Authorization: Bearer $TOKEN")

# The project's .venv, made inside the container as a real user would.
docker exec "$NAME" uv venv --python 3.13 /srv/projects/hello/.venv >/dev/null

cache=$(curl -fsS "${AUTH[@]}" "$BASE/api/monitoring/compile-cache")
[ "$(echo "$cache" | json "d['enabled']")" = "True" ] || { echo "compile cache is off: $cache" >&2; exit 1; }
echo "ok: compile cache on, store in $(echo "$cache" | json "d['directory']")"

build() {
    local body id status
    body='{"project_name":"hello","config":{"project_name":"hello","project_type":"backend_only",
      "source_type":"local","project_path":"/srv/projects/hello","entry_point":"main.py",
      "python_version":"auto","pack_mode":"external","onefile":true,"verify_after_build":true}}'
    id=$(curl -fsS -X POST "${AUTH[@]}" -H 'Content-Type: application/json' "$BASE/api/tasks" -d "$body" | json "d['id']")
    for _ in $(seq 1 600); do
        status=$(curl -fsS "${AUTH[@]}" "$BASE/api/tasks/$id" | json "d['status'].lower()")
        case "$status" in completed|failed|cancelled) break ;; esac
        sleep 2
    done
    if [ "$status" != completed ]; then
        echo "build $id ended $status" >&2
        curl -fsS "${AUTH[@]}" "$BASE/api/tasks/$id/logs" | tail -c 4000 >&2 || true
        return 1
    fi
    echo "$id"
}

first=$(build)
result=$(curl -fsS "${AUTH[@]}" "$BASE/api/history/$first" | json "d['result']")
echo "ok: first build passed: $result" | cut -c1-300
[ "$(curl -fsS "${AUTH[@]}" "$BASE/api/history/$first" | json "d['result']['verify']['status']")" = pass ]

second=$(build)
hits=$(curl -fsS "${AUTH[@]}" "$BASE/api/history/$second" | json "(d['result'].get('compile_cache') or {}).get('hits', 0)")
[ "$hits" -gt 0 ] || { echo "the rebuild reused no C files" >&2; exit 1; }
echo "ok: rebuild reused $hits C files from the compile cache"

# Recreate the container on the same volume: builds, the database and the
# generated session secret must survive, or every upgrade signs everyone out.
docker rm -f "$NAME" >/dev/null
start
count=$(curl -fsS "${AUTH[@]}" "$BASE/api/history" | json "len(d)")
[ "$count" -ge 2 ] || { echo "history lost after recreating the container ($count builds)" >&2; exit 1; }
echo "ok: after recreating the container the old session still works and $count builds are listed"
docker rm -f "$NAME" >/dev/null

# docker-compose.yml as shipped: the first start must create "admin" with a
# random password printed in the log, and that password must sign in.
docker tag "$IMAGE" packwright:local
export COMPOSE_PROJECT_NAME=packwright-smoke
trap 'docker compose logs --tail 100 || true; docker compose down -v >/dev/null 2>&1 || true; cleanup' EXIT
docker compose up -d --no-build >/dev/null
for _ in $(seq 1 90); do
    curl -fsS http://127.0.0.1:5018/health >/dev/null 2>&1 && break
    sleep 1
done
generated=$(docker compose logs packwright 2>&1 | sed -n "s/.*Created bootstrap admin 'admin' with generated password: \([^ ]*\).*/\1/p" | head -1)
[ -n "$generated" ] || { echo "compose start printed no admin password" >&2; exit 1; }
curl -fsS -X POST http://127.0.0.1:5018/auth/login -H 'Content-Type: application/json' \
    -d "{\"username\":\"admin\",\"password\":\"$generated\"}" | json "d['access_token'][:8]" >/dev/null
echo "ok: docker compose up creates admin with the password from the log"
docker compose down -v >/dev/null
trap cleanup EXIT

echo "docker smoke test passed"
