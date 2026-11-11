// Hand-written /ask replies for the screenshot matrix only (PLAN.md Q41): states the real
// fixture can't show. Each is shaped like ask.py public_view() and written in the fixture's
// voice, so the type looks real. Lives in design/, so nothing in the app imports it.
import { EXAMPLE } from "../tests/e2e/mocks";
import type { AskResponse, Citation } from "../lib/types";

const R = EXAMPLE.response;
const PERMALINK = `https://github.com/pallets/itsdangerous/blob/${EXAMPLE.commit_sha}`;

function cite(n: number, path: string, start: number, end: number, block: number): Citation {
  return { n, path, start, end, valid: true, block, url: `${PERMALINK}/${path}#L${start}-L${end}` };
}

/** State 12: ~450 words, the realistic maximum at max_completion_tokens 600 (not 600 words). */
export const LONG_ANSWER: AskResponse = {
  ...R,
  answer: [
    "The library supports key rotation by accepting a list of secret keys instead of a single " +
    "one, and by treating that list as ordered from oldest to newest.",
    "1. **Accepting several keys**: Both `Signer` and `Serializer` take `secret_key` as a string, " +
    "bytes, or an iterable of either. The helper `_make_keys_list` normalises whatever is passed " +
    "into a `list[bytes]` and stores it on the instance as `self.secret_keys` [1](cite:1). A single " +
    "key simply becomes a list with one entry, so code written before rotation existed keeps " +
    "working unchanged.",
    "2. **The order of the list**: The documentation on the attribute states that the list runs " +
    "\"from oldest to newest\" and that \"the newest (last) key is used for signing\" [2](cite:2). " +
    "It also says this is what allows a key rotation system to keep a list of allowed keys and " +
    "remove expired ones. The order is part of the contract, not an implementation detail.",
    "3. **Signing with the newest key**: The `secret_key` property returns `self.secret_keys[-1]`, " +
    "the last entry [3](cite:3). When `derive_key` is called without an explicit key, it falls " +
    "back to the same last entry [4](cite:4). Every new signature is therefore produced with the " +
    "newest key, however many older keys are still listed.",
    "4. **Verifying with every key**: `verify_signature` first decodes the signature and returns " +
    "`False` if it is not valid base64. It then loops over `reversed(self.secret_keys)`, derives a " +
    "key from each secret and asks the signing algorithm to compare signatures [5](cite:5). The " +
    "first match returns `True`; only if no key matches does it return `False`. Trying the newest " +
    "key first means current tokens are checked fastest, while tokens signed with an older key " +
    "still verify as long as that key remains in the list.",
    "5. **The same behaviour in the serializer**: `Serializer` stores its keys with the same helper " +
    "and documents the same oldest-to-newest order [6](cite:6). Its own `secret_key` property also " +
    "returns the last entry [7](cite:7), so serialized payloads follow exactly the same rotation " +
    "rules as raw signatures.",
    "In practice, rotating a key means appending the new key to the end of the list and deploying. " +
    "New tokens are signed with it immediately, while tokens issued earlier keep verifying with the " +
    "older keys. Once every token signed with an old key has expired, that key can be removed from " +
    "the start of the list. Nothing in the library tracks expiry for you: deciding when an old key " +
    "is safe to drop depends on how long your tokens live, for example the `max_age` you pass when " +
    "loading timed tokens.",
  ].join("\n\n"),
};

/** State 14: twelve chips, with adjacent pairs ("[3] [4]" and "[7][8]"). */
export const MANY_CITATIONS: AskResponse = {
  ...R,
  answer:
    "Rotation touches several places in the code. The key list is built by `_make_keys_list` " +
    "[1](cite:1) and normalised to bytes [2](cite:2). The signer documents the order [3](cite:3) " +
    "[4](cite:4) and stores the separator next to it [5](cite:5). Signing uses the newest key " +
    "[6](cite:6), and `derive_key` falls back to it [7](cite:7)[8](cite:8). Verification decodes " +
    "first [9](cite:9), loops from newest to oldest [10](cite:10) and fails only when no key " +
    "matches [11](cite:11). The serializer mirrors all of this [12](cite:12).",
  citations: [
    cite(1, "src/itsdangerous/signer.py", 67, 69, 0),
    cite(2, "src/itsdangerous/signer.py", 70, 73, 0),
    cite(3, "src/itsdangerous/signer.py", 138, 140, 1),
    cite(4, "src/itsdangerous/signer.py", 141, 142, 1),
    cite(5, "src/itsdangerous/signer.py", 143, 144, 1),
    cite(6, "src/itsdangerous/signer.py", 175, 180, 1),
    cite(7, "src/itsdangerous/signer.py", 195, 196, 1),
    cite(8, "src/itsdangerous/signer.py", 197, 200, 1),
    cite(9, "src/itsdangerous/signer.py", 229, 232, 2),
    cite(10, "src/itsdangerous/signer.py", 236, 240, 2),
    cite(11, "src/itsdangerous/signer.py", 242, 242, 2),
    cite(12, "src/itsdangerous/serializer.py", 203, 208, 3),
  ],
};

/** State 13 lives in the e2e mocks, since the layout regression test uses it too (F1). */
export { LONG_LINES } from "../tests/e2e/mocks";

/** State 18: every element an answer may contain, citations inside each, and the Q18
 *  injection input shown as text. */
export const SPECIMEN: AskResponse = {
  ...R,
  answer: [
    "# Key rotation, in brief",
    "The signer keeps a **list of keys [1](cite:1)**, ordered from oldest to newest, and signs " +
    "with the *last* one. Inline code such as `secret_keys[-1]` [3](cite:3) sits in the line.",
    "## How a key is chosen [2](cite:2)",
    "- The newest key signs every new token [3](cite:3)",
    "- **Older keys still verify** [5](cite:5)",
    "  - in order, newest first",
    "1. Append the new key at the end.",
    "2. Remove an old key once its tokens have expired [6](cite:6).",
    "### The verification loop",
    "> Keys are tried from newest to oldest; the first match wins [5](cite:5).",
    "```python\nfor secret_key in reversed(self.secret_keys):\n    key = self.derive_key(secret_key)\n```",
    "---",
    "Injection input, shown as text: <script>alert(1)</script> <img src=x onerror=\"alert(1)\"> " +
    "[a model link](https://evil.example) ![an image](https://evil.example/i.png) [9](cite:9)",
  ].join("\n\n"),
};
