# Decisions

Things that were tried and did not work, with what was measured, so they do not
get tried again by accident.

## The model stays at qwen2.5:3b-instruct

`qwen3:4b` is newer and larger and is already pulled on the server. It was
benchmarked against the running model on the same articles through the same
code path.

| | qwen2.5:3b-instruct | qwen3:4b |
| --- | --- | --- |
| Three articles | 6s | 78s |
| Claims on the chargesheet article | 1, correct | 9, of which 3 correct |

The extra six were invented. It returned that the same person had received a
contract from a company, owned it, approved it, met with it and donated to it,
all from one sentence. Higher recall, much worse precision, thirteen times
slower.

For a project whose whole claim is that every link is sourced, precision is the
thing that matters. **Do not switch without re-measuring.**

Two useful things came out of the test anyway:

- Qwen3 reasons before answering, and Ollama puts that reasoning in a
  `thinking` field while leaving `response` empty. A schema obeyed perfectly
  arrived as zero claims. `"think": false` fixes it, and `extract.py` now sends
  that for any known reasoning model.
- The spray of contradictory relations is detectable. A pair of names now gets
  one relation per article, and a pair offered three or more drops to
  "mentioned with". That helps the model actually in use, not just the one
  rejected.

## Running the model on another machine was rejected

Pointing the server at a laptop with more memory would allow a larger model. It
was not done. The laptop sleeps, moves between networks and has two addresses,
so production would stop whenever it was closed. It would also need a firewall
port opened on the laptop.

## A second model pass to check claims was abandoned

`extract.verify()` exists and is off by default. Asking the model to check its
own claims dropped two correct ones and "corrected" *Chhota Rajan works at
Tihar Jail* to *leads*, which is worse than the error it was fixing.

Deterministic type rules replaced it: a relation must be able to hold between
those two kinds of name. On the test set that caught 4 of 4 nonsense relations
and kept 4 of 4 valid ones. Implausible relations are downgraded rather than
dropped, so the co-appearance survives.

## Sentence embeddings for near duplicates were replaced

The original design used sentence transformers, which meant torch and a model
download to answer "is this the same article I just read". simhash over word
trigrams answers it in microseconds with no dependency. Also removed for the
same reason: GLiNER, ChromaDB, Celery, CrewAI and LangGraph.

## Entity ids no longer include the type

They used to. When the typing rules improved, a name's type changed, its id
changed, and it became a second node with the links split between the two. The
id now comes from the name alone, so re-typing can never split a node.

## Automatic merging: a denylist was the wrong direction

The first version folded two names together unless the extra words were on a
list of words known to change the meaning. That ran on the live graph and made
75 merges, of which a good fraction were wrong:

- `Nationalist Congress Party` into `Congress Party`
- `Tamil Nadu Social Welfare` into `Tamil Nadu Finance`
- two unrelated people into one node

No denylist holds every word that matters. The rule was inverted: fold only
when the difference is an initial or a title, and send everything else to
review. On the same graph the next pass made 3 merges instead of 75, all
correct.

Claims were moved rather than deleted, so no quote or source was lost, but the
names could not be separated again. No backup existed at the time. Backups are
now scheduled, and `scripts/backup.sh` says to run one before bulk changes.

Every pair from that incident is a test case in `tests/test_merge_rules.py`.

## Junk name rules were too aggressive on the first attempt

Rejecting any name with a comma or more than six words would have deleted
`Meta Platforms, Inc`, `Indian Institute of Management, Indore` and
`Agricultural and Processed Food Products Export Development Authority`.

The rules now reject a comma followed by a whole phrase, more than ten words,
a leading lowercase word, list markers like "including" and "others", and a
stray possessive `s` left behind by punctuation stripping. Both directions are
tested.

## "Union" was removed from the party word list

It typed `Union Home Affairs Ministry` and `States and Union Territories` as
political parties, which put government bodies on the parties page. In Indian
government naming it means the centre. Court and government words are now
checked before the looser party words.

## Health is judged on progress, not on ports

An earlier status page asked whether Ollama was listening and reported
everything healthy while the worker was dead and the queue had grown to
thousands. Every moving part now writes a heartbeat, and health is judged on
whether work is happening.

## Data lives in named volumes

An earlier version kept it in a folder inside the repository, on a path that
was cloud synced. The folder was cleared and everything went with it. Named
volumes survive reboots, rebuilds and moving the project folder.
