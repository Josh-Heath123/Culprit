# Demonstration video — recording checklist

Work through this top to bottom before recording, and again for any
re-take. It exists so the video can only show what works
(`docs/PRODUCTISATION.md` §7; standard 3).

## Before

- [ ] **A fresh clone of `main`**, outside any temp folder, at a commit whose
      CI run is green — including the `e2e` job. Note the commit in the
      video description.
- [ ] Docker running with at least 8 GB free; nothing else on port 8088.
- [ ] `QUICKSTART_HTTP_PORT=8088 just quickstart` exits 0 and prints
      `/investigations/<id>` with root
      `auth:order-service->inventory-service/audience`. Copy the admin
      login it prints; do not show it on screen.
- [ ] `just e2e` passes against that stack. This also posts the three
      partial investigations scene 11 needs.
- [ ] `just cli-build` and `(cd extractors/node && npm ci)`; `culprit` on
      `PATH`.
- [ ] The README "Usage" commands for `env capture` and `diff` run as
      written (scene 5), in a scratch directory.
- [ ] The diagrams render (scenes 2 and 12): GitHub's README view, or a
      Mermaid render saved as an image.

## Screen

- [ ] Terminal: dark theme, a monospace font at 18 pt or larger, 100×30,
      prompt shortened to `$`. No shell history visible, no hostname or user
      name in the prompt.
- [ ] Browser: 1280×800 window, zoom 100%, no extensions or bookmarks bar,
      a fresh profile. Signed in before recording; never type the password
      on camera.
- [ ] Notifications off; nothing personal in any window or tab title.

## Data

- [ ] Synthetic only: the demo services, the quickstart's injected fault,
      the fault library's recordings. No real repository, environment,
      token or address appears anywhere.
- [ ] The token a probe reads is redacted in every reading on screen
      (`[REDACTED]` or a shape) — check scene 9's reading before recording.

## During

- [ ] Each CLI scene is one real run, recorded as it happens. Cuts are
      allowed to skip waiting (a build); never to splice output from two
      runs together.
- [ ] Read the script as written; where the screen and the script
      disagree, stop and fix the script.

## After

- [ ] Watch it through once against the storyboard: every claim made is
      visible on screen at that moment.
- [ ] Upload, then add the link to the README (near the top, §2 of the
      README structure). Not before: the README links a video only once it
      exists.
- [ ] `just quickstart-down` and remove the clone.
