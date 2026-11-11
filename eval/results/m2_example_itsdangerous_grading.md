# Example answer to grade (slice 3 fixture)
Source: `frontend/data/examples/pallets__itsdangerous.json` (attempt 2, 2026-11-02 21:36 UTC,
qwen/qwen3.8-27b, prompt v3, temperature 0, commit `672971d`). Citations are shown as `[n]`;
the server marked all 7 valid (strict).

Grade with the three columns (PLAN.md, "M2 model comparison"):
- **correct** (against the source): correct / partial / wrong
- **grounded** (against the code the model was given, below): yes / partly (a minor unsupported
  detail) / no (the central claim is unsupported)
- **citations valid**: 7/7 strict (server check, already measured)

## Question
How does it support rotating to a new secret key while old keys still work?

## Answer
The library supports key rotation by accepting an iterable of secret keys and storing them as a
list ordered from oldest to newest.

1. **Key Storage**: Both `Signer` and `Serializer` accept `secret_key` as a string, bytes, or an
   iterable. The helper function `_make_keys_list` converts this into a `list[bytes]` stored in
   `self.secret_keys` [1]. The documentation explicitly states this list is ordered "from oldest
   to newest" [2].
2. **Signing**: When signing data, the system uses the newest key. The `secret_key` property
   returns the last item in the list (`self.secret_keys[-1]`), which is used by default in
   `derive_key` [3] [4].
3. **Verification**: When verifying a signature, the system iterates through the keys in reverse
   order (newest to oldest). The `verify_signature` method loops through
   `reversed(self.secret_keys)`, deriving a key for each and checking if the signature matches.
   It returns `True` as soon as a valid key is found [5]. This allows old signatures to remain
   valid as long as their corresponding key is still in the list.
4. **Serializer Support**: The `Serializer` class implements the same logic, storing
   `secret_keys` via `_make_keys_list` and providing a `secret_key` property that returns the
   newest key [6] [7].

## What each citation points to (exact lines)
**[1] src/itsdangerous/signer.py:67-73**
```
67| def _make_keys_list(
68|     secret_key: str | bytes | cabc.Iterable[str] | cabc.Iterable[bytes],
69| ) -> list[bytes]:
70|     if isinstance(secret_key, (str, bytes)):
71|         return [want_bytes(secret_key)]
72|
73|     return [want_bytes(s) for s in secret_key]  # pyright: ignore
```

**[2] src/itsdangerous/signer.py:138-142**
```
138|         #: The list of secret keys to try for verifying signatures, from
139|         #: oldest to newest. The newest (last) key is used for signing.
140|         #:
141|         #: This allows a key rotation system to keep a list of allowed
142|         #: keys and remove expired ones.
```

**[3] src/itsdangerous/signer.py:175-180**
```
175|     @property
176|     def secret_key(self) -> bytes:
177|         """The newest (last) entry in the :attr:`secret_keys` list. This
178|         is for compatibility from before key rotation support was added.
179|         """
180|         return self.secret_keys[-1]
```

**[4] src/itsdangerous/signer.py:195-196**
```
195|         if secret_key is None:
196|             secret_key = self.secret_keys[-1]
```

**[5] src/itsdangerous/signer.py:227-242**
```
227|     def verify_signature(self, value: str | bytes, sig: str | bytes) -> bool:
228|         """Verifies the signature for the given value."""
229|         try:
230|             sig = base64_decode(sig)
231|         except Exception:
232|             return False
233|
234|         value = want_bytes(value)
235|
236|         for secret_key in reversed(self.secret_keys):
237|             key = self.derive_key(secret_key)
238|
239|             if self.algorithm.verify_signature(key, value, sig):
240|                 return True
241|
242|         return False
```

**[6] src/itsdangerous/serializer.py:203-208**
```
203|         #: The list of secret keys to try for verifying signatures, from
204|         #: oldest to newest. The newest (last) key is used for signing.
205|         #:
206|         #: This allows a key rotation system to keep a list of allowed
207|         #: keys and remove expired ones.
208|         self.secret_keys: list[bytes] = _make_keys_list(secret_key)
```

**[7] src/itsdangerous/serializer.py:236-241**
```
236|     @property
237|     def secret_key(self) -> bytes:
238|         """The newest (last) entry in the :attr:`secret_keys` list. This
239|         is for compatibility from before key rotation support was added.
240|         """
241|         return self.secret_keys[-1]
```

## The full context the model was given
For the **grounded** column: the model saw exactly these four blocks and nothing else
(`signer.py` 67-73, 129-213, 227-242; `serializer.py` 190-241). They are in the fixture under
`response.blocks`; the cited lines above are taken from them. The rest of 129-213 is
`Signer.__init__` (the key list, separator, salt, key derivation, digest and algorithm setup),
the `secret_key` property and the whole of `derive_key`; the rest of serializer.py 190-241 is
`Serializer.__init__` and its `secret_key` property. `get_signature` and `sign` (signer.py
215-225) were not supplied.

## Grade (by Claude; spot-checked and agreed by the author)
- correct: **correct**
- grounded: **yes**
- citations valid: 7/7 strict
- graded by / date: **Claude**, in the mentor review chat, at the author's request, 2026-11-03.
- author spot-check: **done, 2026-11-11, Umar Javed; agrees with the grade.** The three checks,
  against the code at `672971d`: the `reversed(self.secret_keys)` loop ([5], lines 236-240),
  the "oldest to newest" comment ([2], lines 138-142) and `return self.secret_keys[-1]`
  ([3], lines 175-180). In the fixture: `grade.reviewer: "author"`.
- note: every claim checked against the four supplied blocks. The answer explains the
  mechanism fully but omits the practical rotation step (add the new key last, remove old
  ones later), so it is slightly incomplete. Attempts 1 and 2 differ only in
  minor ways, not materially (same claims; the closing paragraph is dropped and citation 5 is
  broader). Since the author's spot-check (2026-11-11), the page says "Checked by the author."
