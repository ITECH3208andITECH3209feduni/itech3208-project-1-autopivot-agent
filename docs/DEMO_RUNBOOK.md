# Demo runbook — AutoPivot on RunPod

Bring the platform up on a GPU pod and walk a client through it.

> **Do a full dry run before the day.** The pipeline has never processed an image
> against real models — everything so far was verified against a stub. The first
> real run is a test, not a demo. Do it privately, then repeat it live.

---

## 1. Create the pod

| Setting | Choose | Why |
|---|---|---|
| GPU | RTX 4000 Ada, 3090 or A4000 | Segmentation runs at 1024×1024. An A100 burns credits for no gain. |
| Template | Any PyTorch image | torch arrives matched to the CUDA driver. Installing a generic wheel breaks GPU detection. |
| **Network volume** | **Attach one, mounted at `/workspace`** | Without it the database and every image are destroyed when the pod is terminated. |
| Container disk | 30 GB or more | Model weights are a couple of gigabytes. |

Skip the volume and you rebuild everything each session.

---

## 2. Clone

The repository is private, so this needs a GitHub personal access token with read
access. Use a credential helper — a token pasted into the clone URL is written to
`.git/config` and stays there.

```bash
cd /workspace && git clone https://github.com/ITECH3208andITECH3209feduni/itech3208-project-1-autopivot-agent.git && cd itech3208-project-1-autopivot-agent
```

---

## 3. Bring everything up

```bash
bash scripts/runpod_up.sh
```

One command: PostgreSQL, dependencies, schema, dealership, client build, API and
a public tunnel. It skips anything already done, so re-running costs seconds.

It finishes with a box containing the **public URL, email and password**. Expect
5–15 minutes on a cold pod, most of it downloading model weights.

Add `HF_TOKEN` first if you want RMBG-2.0 rather than the BiRefNet fallback.
BiRefNet works fine; it is simply second choice.

```bash
export HF_TOKEN=hf_your_token_here
```

### Confirm before going further

```bash
bash scripts/runpod_up.sh --status
```

Then check the log says the GPU was found:

```bash
grep -o 'device=[a-z]*' /workspace/autopivot-app.log | tail -1
```

**`device=cuda`** is required. If it says `cpu`, stop and fix that — CPU
inference will look like the application is broken when it is only slow.

---

## 4. Sign in

```
Email     ana.reid@northshore.co.nz
Password  autopivot-demo-2026
```

**Type the password. Do not paste it.** A password manager will happily fill a
saved credential over what you type, and the server then rejects a password you
never sent. This has already cost one session — if login fails, open DevTools →
Network → `login` → Payload and read what was actually transmitted before
assuming the password is wrong.

---

## 5. The demo

Order matters — each step depends on the one before.

**1. Backdrops → Upload backdrop.** A scene the vehicle will be composited onto.
The library starts empty because backdrops belong to the dealership, not to
AutoPivot.

**2. New vehicle.** Make, model and year, then attach photographs. Two or three
is plenty; every extra photo is another GPU pass to wait through.

**3. Start processing**, choosing the backdrop. The Processing screen polls and
shows each job as it lands.

**4. Results.** Processed images beside their originals.

### Worth pointing out while it runs

- The library is **per dealership**. Another dealership cannot see these
  backdrops or vehicles — enforced by the database, not by application code.
- A photograph with no vehicle in it comes back **needs review**, not failed.
  The run was correct; the result needs a person.
- **Number plates are blurred automatically**, and a detection is rejected
  unless it is plate-shaped, plate-sized and sitting on the car. Worth saying
  out loud: the system would rather miss a plate than obscure the wrong part of
  a photograph the dealer is about to publish.

### Do not promise

- **Angle matching.** Nothing computes a shot angle yet. The backdrop is the one
  you chose, not one selected to match the photograph.
- **Listing URL import on any given site.** It is connected now, but it fails on
  carsales (blocks automated requests) and autotrader (gallery is built in the
  browser). If you demonstrate it, use a site you have tested beforehand, or
  demonstrate the failure deliberately — the error names the reason, which is
  the point worth showing.
- **Password reset and adding staff.** Not built.

---

## 6. If something breaks

**Login rejected.** Read the server log — it distinguishes the two causes, while
the browser deliberately cannot:

```bash
grep "Login rejected" /workspace/autopivot-app.log | tail -3
```

`bad password for user_id=1` means the account is fine and the browser sent
something else. `unknown email` means the app is pointed at the wrong database.

**Processing fails.** The traceback is in the app log, and the job records as
failed rather than taking the batch down:

```bash
tail -50 /workspace/autopivot-app.log
```

**Nothing loads.** Check both processes are alive:

```bash
bash scripts/runpod_up.sh --status
```

**The tunnel URL changed.** It is regenerated whenever the tunnel restarts.
`--status` prints the current one.

---

## 7. Before shutting down

The database lives on the container filesystem unless the volume allowed
PostgreSQL to own its directory. Back it up or you rebuild next time:

```bash
bash scripts/runpod_up.sh --backup
```

Then stop the pod from the RunPod console. Files and configuration on
`/workspace` persist; the signing key and admin password are reused, so the
next `runpod_up.sh` returns you to exactly this state.

---

## Known limits, stated plainly

Worth having ready if someone asks a sharp question.

- The pipeline had never run against real models before this deployment.
- `/process-vehicle`, `/remove-background`, `/detect-and-hide` and
  `/extract-images-from-url` have no authentication. Anyone with the URL can use
  the GPU. Acceptable for a short session on an unlisted URL, not for anything
  left running.
- Everyone shares one account; there is no user management yet.
- Listing-URL import is limited to sites that serve their images in the initial
  HTML. Others return an error naming the reason rather than silently importing
  nothing.
- Compositing is a straight paste: no contact shadow, no ground reflection and
  no colour matching between the vehicle and the backdrop. The cars read as
  placed on the scene rather than photographed in it. Work in progress.
