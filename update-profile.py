"""Regenerate dark-mode.svg / light-mode.svg with live GitHub stats.

Runs daily via GitHub Actions. Stdlib only, no dependencies.
"""
import html
import json
import os
import urllib.request
from datetime import datetime, timezone

USER = "AltafHunzai"
W = 70  # info column width in characters
ART = r"""
                 ++==---
            +==---------:-:::
          +==------::::::..... .
        *===----:::::...::::..   :#
       +==-=========++++++++==:.  .#
      =--=+*#%%######******++++-:  +
      -=*#%%%%%%#####*******+++=-:.=
      =*%%@@@@%%%######******+++=-:-
      +#%%##*+++*###**+----===+++=--#
      +#%#+===::-+##*=::::::-==++=--=*
    %#*#%#*+*+-=+#%%*=---:---=++++==+=   #
    %#*#%%%%%###%%%%*+++++++***+++=-=+##**
    @#+#%%%%%%%%%%%#*++++***+++++++==*###
     %###%%%%#####++=-=+++**+++++++++
      %%########%%#+++++++**++==+++*
        ##*###**#**++====++*++++++
         *##%#**##*++++++++*+++==*
          *###%%%##******+++++===+
           **##%%%#*****++====-==
         #+#*+++++=====------==++.
         ..%##*+=------:---===++=-.
     #+   :%%%%#*+=----====+++++=-.
 *+    .  :#%%###*++====++++*+++=-
       .  :+######****++*****+++=
          :+**#####************=
           :+***####***##****+:
             -+*##########+==.
               .=*#####*=.
"""

# two tokens by design: the Actions GITHUB_TOKEN yields the contribution-style
# commit count (public + private activity), while a PAT (ACCESS_TOKEN secret)
# sees private repos for the repo list and LOC walk. Either falls back to the other.
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("ACCESS_TOKEN") or ""
PRIV_TOKEN = os.environ.get("ACCESS_TOKEN") or TOKEN


def gh(url, payload=None, token=None):
    auth_token = token or TOKEN
    if not auth_token:
        raise RuntimeError("Set GITHUB_TOKEN or ACCESS_TOKEN to fetch GitHub profile stats")
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode() if payload else None,
        headers={"Authorization": f"Bearer {token or TOKEN}", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req) as r:
        return r.status, json.loads(r.read() or "{}")


def graphql(query, variables=None, token=None):
    _, resp = gh("https://api.github.com/graphql", {"query": query, "variables": variables or {}}, token)
    if resp.get("errors"):
        raise RuntimeError(resp["errors"])
    return resp["data"]


def fetch_stats():
    created_at = graphql(
        f'query {{ user(login: "{USER}") {{ createdAt }} }}'
    )["user"]["createdAt"]
    joined_year = int(created_at[:4])
    yr_aliases = "\n".join(
        f'y{y}: contributionsCollection(from: "{y}-01-01T00:00:00Z", to: "{y + 1}-01-01T00:00:00Z")'
        " { totalCommitContributions restrictedContributionsCount }"
        for y in range(joined_year, datetime.now(timezone.utc).year + 1)
    )
    contrib = graphql(f'query {{ user(login: "{USER}") {{ {yr_aliases} }} }}')["user"]
    commits = sum(
        v["totalCommitContributions"] + v["restrictedContributionsCount"]
        for v in contrib.values()
    )
    u = graphql(f"""
    query {{
      user(login: "{USER}") {{
        id
        followers {{ totalCount }}
        repositories(first: 100, ownerAffiliations: OWNER) {{
          totalCount
          nodes {{ name stargazerCount isFork }}
        }}
        repositoriesContributedTo(first: 1, contributionTypes: [COMMIT, PULL_REQUEST, REPOSITORY]) {{
          totalCount
        }}
      }}
    }}""", token=PRIV_TOKEN)["user"]
    stats = {
        "followers": u["followers"]["totalCount"],
        "repos": u["repositories"]["totalCount"],
        "contributed": u["repositoriesContributedTo"]["totalCount"],
        "stars": sum(n["stargazerCount"] for n in u["repositories"]["nodes"]),
        "commits": commits,
    }
    stats.update(loc([n["name"] for n in u["repositories"]["nodes"] if not n["isFork"]], u["id"]))
    return stats


LOC_QUERY = """
query($owner: String!, $name: String!, $id: ID!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef { target { ... on Commit {
      history(first: 100, author: {id: $id}, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes { additions deletions }
      }
    } } }
  }
}"""


def loc(repo_names, user_id):
    # ponytail: REST stats/contributors answers 202 forever to the Actions token,
    # so walk own commits on the default branch via GraphQL instead
    add = rem = 0
    for name in repo_names:
        cursor = None
        try:
            while True:
                ref = graphql(LOC_QUERY, {"owner": USER, "name": name, "id": user_id, "cursor": cursor}, token=PRIV_TOKEN)["repository"]["defaultBranchRef"]
                if ref is None:
                    break  # empty repo
                h = ref["target"]["history"]
                add += sum(n["additions"] for n in h["nodes"])
                rem += sum(n["deletions"] for n in h["nodes"])
                if not h["pageInfo"]["hasNextPage"]:
                    break
                cursor = h["pageInfo"]["endCursor"]
        except Exception as e:
            print(f"loc {name}: {e}")
    return {"loc_add": add, "loc_del": rem, "loc": add - rem}


PALETTES = {
    "dark": {"bg": "#0d1117", "border": "#30363d", "art": "#8b949e", "h": "#58a6ff",
             "k": "#ffa657", "v": "#c9d1d9", "d": "#484f58", "g": "#3fb950", "r": "#f85149"},
    "light": {"bg": "#ffffff", "border": "#d0d7de", "art": "#57606a", "h": "#0969da",
              "k": "#953800", "v": "#24292f", "d": "#afb8c1", "g": "#1a7f37", "r": "#cf222e"},
}


def kv(key, val, width=W):
    dots = "." * max(width - len(key) - len(str(val)) - 3, 1)
    return [(f"{key}: ", "k"), (dots + " ", "d"), (str(val), "v")]


def kv2(k1, v1, k2, v2):
    left = kv(k1, v1, 30)
    return left + [(" | ", "d")] + kv(k2, v2, 23)


def rule(title=""):
    label = f"─ {title} " if title else ""
    return [(label, "h"), ("─" * (W - len(label)), "d")]


def info_lines(s):
    n = lambda x: f"{x:,}"
    stats_lines = (
        [
            kv2("Repos", f"{s['repos']} {{Contributed: {s['contributed']}}}", "Stars", n(s["stars"])),
            kv2("Commits", n(s["commits"]), "Followers", n(s["followers"])),
            [("Lines of Code: ", "k"), (n(s["loc"]), "v"), (" ( ", "d"),
             (n(s["loc_add"]) + "++", "g"), (", ", "d"), (n(s["loc_del"]) + "--", "r"), (" )", "d")],
        ]
        if s
        else [[("Live stats refresh automatically through GitHub Actions.", "v")]]
    )
    return [
        [(f"{USER.lower()}@github ", "h"), ("─" * (W - len(USER) - 8), "d")],
        [],
        kv("Role", "Full-Stack Web Developer"),
        kv("Experience", "5+ years"),
        kv("Focus", "Front-end, back-end, mobile apps"),
        [],
        kv("Languages", "JavaScript, TypeScript, PHP"),
        kv("Languages.Real", "Urdu, English"),
        kv("Frameworks", "React, Next.js, Laravel, Svelte"),
        kv("Learning", "CI/CD, DevOps"),
        kv("IDE", "Claude Code, Cursor, VS Code, Antigravity"),
        [],
        rule("Contact"),
        kv("Email", "altafdev804@gmail.com"),
        kv("LinkedIn", "altaf-hussain-5aa663213"),
        [],
        rule("GitHub Stats"),
        *stats_lines,
    ]


def render(mode, stats):
    p = PALETTES[mode]
    out = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1020" height="520" viewBox="0 0 1020 520" '
        f'font-family="Consolas, Menlo, monospace" font-size="13px">',
        f'<rect x="0.5" y="0.5" width="1019" height="519" rx="10" fill="{p["bg"]}" stroke="{p["border"]}"/>',
        f'<rect x="30" y="30" width="360" height="460" rx="12" fill="{p["bg"]}" stroke="{p["border"]}"/>',
        '<title>Altaf Hussain GitHub profile</title>',
        f'<line x1="410" y1="35" x2="410" y2="485" stroke="{p["border"]}"/>',
    ]
    for i, line in enumerate(ART.strip("\n").splitlines()):
        out.append(
            f'<text x="42" y="{72 + i * 14:.1f}" fill="{p["art"]}" '
            f'font-size="13px" xml:space="preserve">{html.escape(line)}</text>'
        )
    for i, segs in enumerate(info_lines(stats)):
        if not segs:
            continue
        spans = "".join(f'<tspan fill="{p[c]}">{html.escape(t)}</tspan>' for t, c in segs)
        out.append(f'<text x="440" y="{45 + i * 21}" xml:space="preserve">{spans}</text>')
    out.append("</svg>")
    return "\n".join(out)


def selfcheck():
    assert len("".join(t for t, _ in kv("Role", "Full-Stack Web Developer"))) == W
    assert len(ART.strip("\n").splitlines()) == 28


if __name__ == "__main__":
    selfcheck()
    stats = fetch_stats()
    print("stats:", stats)
    for mode in PALETTES:
        with open(f"{mode}-mode.svg", "w", encoding="utf-8") as f:
            f.write(render(mode, stats))
    print("wrote dark-mode.svg, light-mode.svg")