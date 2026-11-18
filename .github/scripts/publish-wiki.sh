#!/bin/sh
# Publishes the wiki/ folder to the GitHub Wiki (used by .github/workflows/wiki.yml).
# wiki/ is the source of truth: any edits should be made in wiki/, not directly on the wiki.
#
# Prerequisite (once): in GitHub Settings > Features, enable Wikis and create
# any initial page in the Wiki tab so the .wiki.git repository exists.
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd)
if [ -n "${WIKI_URL:-}" ]; then
    url=$WIKI_URL
else
    url="https://github.com/${GITHUB_REPOSITORY:?Set GITHUB_REPOSITORY (owner/repo) or WIKI_URL}.wiki.git"
fi

# Pass token via HTTP header rather than embedding credentials in the remote URL.
auth=
if [ -n "${WIKI_TOKEN:-}" ]; then
    auth="http.extraheader=AUTHORIZATION: basic $(printf 'x-access-token:%s' "$WIKI_TOKEN" | base64 | tr -d '\n')"
fi
gitw() {
    if [ -n "$auth" ]; then git -c "$auth" "$@"; else git "$@"; fi
}

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

if ! gitw clone -q --depth 1 "$url" "$work/wiki"; then
    echo "Could not clone the wiki ($url). Does it exist? In Settings > Features, enable Wikis," >&2
    echo "open the Wiki tab, create an initial page, and re-run the workflow." >&2
    exit 1
fi

find "$work/wiki" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp -R "$root/wiki/." "$work/wiki/"

cd "$work/wiki"
git add -A
if git diff --cached --quiet; then
    echo "The wiki already matches the wiki/ folder."
    exit 0
fi

git -c core.quotepath=false diff --cached --stat
rev=${GITHUB_SHA:-$(git -C "$root" rev-parse HEAD)}
git -c user.name="github-actions[bot]" \
    -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
    commit -q -m "Publish wiki from wiki/ at $(printf %.7s "$rev")"
gitw push -q origin HEAD
echo "Wiki published."
