# Roadmap

course-grader's backlog, tracked with [roadmap-core](https://github.com/gald33/roadmap-core)
on its SQLite floor: no server, no token.

```bash
pip install "roadmap-core[files]"
export ROADMAP_SOURCE=local

roadmap push              # roadmap/items/*.yaml -> roadmap/roadmap.db (do this first)
roadmap ready             # what is startable, most important first
roadmap show <key>        # one item, with its evidence
roadmap claim <key>       # take it before starting; roadmap release <key> to drop it
roadmap validate          # schema, dangling deps, cycles, missing evidence
roadmap sync              # regenerate roadmap/ROADMAP.md and ARCS.md
roadmap doctor            # if anything looks off
```

- **Adding an item means writing `roadmap/items/<key>.yaml`**, then `roadmap push` and
  `roadmap sync`, and committing all three. Every item needs `evidence`: why it's worth
  doing and how you'll know it's done.
- **`roadmap/ROADMAP.md` and the root `ARCS.md` are generated.** Don't edit them by hand,
  and don't move `ARCS.md`: the path is fixed, and CI (`.github/workflows/roadmap.yml`)
  fails when either file is stale.
- **`roadmap/roadmap.db` is not committed.** It's rebuilt from the YAML files.
