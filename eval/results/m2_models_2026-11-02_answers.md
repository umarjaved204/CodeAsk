# M2 model comparison: answers to grade
Grade each answer: correct / partial / wrong (unanswerable: correct = says the files don't contain it).

## Q1 · qwen/qwen3.8-27b
**How is the signing key derived from the secret key?**

The signing key is derived in `derive_key` [1](cite:1). It first selects the secret key: if none is passed, it uses the last entry in `secret_keys` (the newest key); otherwise it converts the provided key to bytes [2](cite:2).

Then it applies one of four methods based on `self.key_derivation`:

- **`concat`**: hashes `salt + secret_key` with the digest method [3](cite:3).
- **`django-concat`** (the default, set by `default_key_derivation` [4](cite:4)): hashes `salt + b"signer" + secret_key` [5](cite:5).
- **`hmac`**: creates an HMAC using the secret key as the key and the salt as the message, then returns the digest [6](cite:6).
- **`none`**: returns the secret key unchanged [7](cite:7).

Any other value raises `TypeError` [8](cite:8).

The `key_derivation` parameter defaults to `default_key_derivation` (`"django-concat"`) if not supplied [9](cite:9). The docstring notes key derivation is not intended as a security method for turning short passwords into complex keys; large random secret keys should be used [10](cite:10).

- [1] ok src/itsdangerous/signer.py:182-213
- [2] ok src/itsdangerous/signer.py:195-198
- [3] ok src/itsdangerous/signer.py:200-201
- [4] ok src/itsdangerous/signer.py:127-127
- [5] ok src/itsdangerous/signer.py:202-205
- [6] ok src/itsdangerous/signer.py:206-209
- [7] ok src/itsdangerous/signer.py:210-211
- [8] ok src/itsdangerous/signer.py:212-213
- [9] ok src/itsdangerous/signer.py:160-163
- [10] ok src/itsdangerous/signer.py:183-187

**Grade:** correct

## Q1 · openai/gpt-oss-120b
**How is the signing key derived from the secret key?**

The signing key is produced by the **`derive_key`** method of `Signer`.  

1. If no `secret_key` argument is given, the method uses the newest secret key (`self.secret_keys[-1]`) otherwise it converts the provided key to bytes (`want_bytes`)【src/itsdangerous/signer.py:195-199】.  

2. The actual derivation depends on the `key_derivation` setting:  

   * **`concat`** – returns the digest of the salt concatenated with the secret key【src/itsdangerous/signer.py:200-202】.  
   * **`django-concat`** – returns the digest of the salt, the literal bytes `b"signer"`, and the secret key【src/itsdangerous/signer.py:202-205】.  
   * **`hmac`** – creates an HMAC object with the secret key as the key, updates it with the salt, and returns the HMAC digest【src/itsdangerous/signer.py:206-209】.  
   * **`none`** – returns the secret key unchanged【src/itsdangerous/signer.py:210-211】.  

If an unknown `key_derivation` value is supplied, a `TypeError` is raised【src/itsdangerous/signer.py:212-213】.  

Thus, the signing key is derived by applying one of these algorithms (default is `"django-concat"` as defined in the class) to the secret key and the configured salt.


**Grade:** correct – citations in its own format, not parsed

## Q2 · qwen/qwen3.8-27b
**How does it check that a timestamped signature hasn't expired (max_age)?**

The expiration check happens in `TimestampSigner.unsign` after the signature is successfully verified and the timestamp is parsed.

1.  **Calculate Age**: It computes the age of the signature by subtracting the signed timestamp (`ts_int`) from the current timestamp (`self.get_timestamp()`).
    *   [1](cite:1)

2.  **Compare to `max_age`**: If `max_age` is provided, it checks if the calculated `age` is greater than `max_age`.
    *   [2](cite:2)

3.  **Raise Exception**: If the signature is too old (`age > max_age`), it raises a `SignatureExpired` exception with a message indicating the age exceeded the limit. It also handles the edge case where the age is negative (clock skew/future timestamp) by raising `SignatureExpired` as well.
    *   [3](cite:3)

The `TimedSerializer.loads` method forwards the `max_age` argument to the signer's `unsign` method, allowing the serializer to enforce expiration limits during deserialization.
*   [4](cite:4)

- [1] ok src/itsdangerous/timed.py:139-139
- [2] ok src/itsdangerous/timed.py:138-141
- [3] ok src/itsdangerous/timed.py:142-153
- [4] ok src/itsdangerous/timed.py:204-206

**Grade:** correct

## Q2 · openai/gpt-oss-120b
**How does it check that a timestamped signature hasn't expired (max_age)?**

The check is performed inside **`TimestampSigner.unsign`**.

1. After extracting the integer timestamp (`ts_int`) from the signed value, the method looks at the optional `max_age` argument.  
2. If `max_age` is provided, it computes the age of the signature as the difference between the current timestamp (`self.get_timestamp()`) and the stored timestamp (`ts_int`)【src/itsdangerous/timed.py:138-140】.  
3. It then compares this age to `max_age`:  

   * If the age is **greater** than `max_age`, a `SignatureExpired` exception is raised with a message indicating the signature is too old【src/itsdangerous/timed.py:141-144】.  
   * If the age is **negative** (the timestamp is in the future), it also raises `SignatureExpired` because the signature appears to be from the future【src/itsdangerous/timed.py:148-152】.

Thus, the expiration check consists of calculating `age = current_time - stored_time` and raising `SignatureExpired` when `age` is outside the allowed range (`age > max_age` or `age < 0`).


**Grade:** correct

## Q3 · qwen/qwen3.8-27b
**How does the URL-safe serializer compress the payload?**

The URL-safe serializer compresses the payload using **zlib** compression, applied conditionally in `dump_payload` [1](cite:1):

1. It first serializes the object to JSON via `super().dump_payload(obj)` [2](cite:2).
2. It compresses that JSON with `zlib.compress(json)` [3](cite:3).
3. It only uses the compressed version if it is shorter than the original minus one byte: `if len(compressed) < (len(json) - 1)` [4](cite:4). The `-1` accounts for the `b"."` prefix added to mark compressed payloads.
4. If compressed, it prepends a `b"."` byte to the base64-encoded result [5](cite:5).

On load, `load_payload` detects compression by checking `payload.startswith(b".")` [6](cite:6), strips the byte, base64 decodes, then decompresses with `zlib.decompress` [7](cite:7).

The base64 encoding uses a URL-safe alphabet consisting of ASCII letters, digits, `-`, `_`, and `=` [8](cite:8).

This mixin is used by both `URLSafeSerializer` [9](cite:9) and `URLSafeTimedSerializer` [10](cite:10).

- [1] ok src/itsdangerous/url_safe.py:55-69
- [2] ok src/itsdangerous/url_safe.py:56-56
- [3] ok src/itsdangerous/url_safe.py:58-58
- [4] ok src/itsdangerous/url_safe.py:60-62
- [5] ok src/itsdangerous/url_safe.py:66-67
- [6] UNVERIFIED src/itsdangerous/url_safepy:32-34
- [7] ok src/itsdangerous/url_safe.py:44-51
- [8] ok src/itsdangerous/encoding.py:41-42
- [9] ok src/itsdangerous/url_safe.py:72-76
- [10] ok src/itsdangerous/url_safe.py:79-83

**Grade:** partial – says the base64 alphabet includes '=' (true of the constant at encoding.py:41-42, but base64_encode strips padding; also off-topic)

## Q3 · openai/gpt-oss-120b
**How does the URL-safe serializer compress the payload?**

The URL‑safe serializer mixes in **URLSafeSerializerMixin**, which overrides the normal `dump_payload` method.

1. It first obtains the JSON bytes from the parent serializer (`super().dump_payload(obj)`)【src/itsdangerous/url_safe.py:55-57】.  
2. It compresses those bytes with **zlib.compress** and stores the result in `compressed`【src/itsdangerous/url_safe.py:58】.  
3. It compares the length of the compressed data with the original JSON length minus one; if the compressed version is at least one byte smaller, it replaces the JSON payload with the compressed data and sets `is_compressed = True`【src/itsdangerous/url_safe.py:60-63】.  
4. The (possibly compressed) payload is then base64‑url‑encoded (`base64_encode`)【src/itsdangerous/url_safe.py:64】.  
5. If compression was applied, a leading dot (`b"."`) is prepended to the encoded bytes to signal that the payload must be decompressed on load【src/itsdangerous/url_safe.py:66-68】.

During loading, `load_payload` checks for this leading dot, strips it, and if present runs `zlib.decompress` after base64‑decoding【src/itsdangerous/url_safe.py:30-35】【src/itsdangerous/url_safe.py:44-51】. Thus the serializer compresses the payload with zlib only when it reduces the size, and marks it with a leading “.” for later decompression.


**Grade:** correct

## Q4 · qwen/qwen3.8-27b
**How does base64 decoding handle missing padding and errors?**

Based on the provided files, `base64_decode` handles missing padding and errors as follows:

1.  **Missing Padding:** The function first converts the input to bytes using `want_bytes` with ASCII encoding and ignoring errors. It then manually adds the necessary padding characters (`=`) to ensure the string length is a multiple of 4 before decoding [1](cite:1).
2.  **Errors:** The actual decoding is performed using `base64.urlsafe_b64decode`. If this operation raises a `TypeError` or `ValueError`, the function catches the exception and raises a `BadData` exception with the message "Invalid base64-encoded data" [2](cite:2).

The `BadData` exception is imported from `.exc` [3](cite:3).

- [1] ok src/itsdangerous/encoding.py:32-33
- [2] ok src/itsdangerous/encoding.py:35-38
- [3] ok src/itsdangerous/encoding.py:8-8

**Grade:** correct

## Q4 · openai/gpt-oss-120b
**How does base64 decoding handle missing padding and errors?**

`base64_decode` first ensures the input is a bytes object, then adds any missing “=” padding so the length is a multiple of 4, and finally calls the standard library decoder. If the underlying `base64.urlsafe_b64decode` raises a `TypeError` or `ValueError` (e.g., because the data is not valid base64), the function catches the exception and re‑raises it as a `BadData` error.

* The padding is added with `string += b"=" * (-len(string) % 4)` [encoding.py:32‑34].
* The actual decode is performed by `base64.urlsafe_b64decode(string)` [1](cite:1).
* Errors are caught with `except (TypeError, ValueError) as e:` and re‑raised as `BadData("Invalid base64-encoded data")` [encoding.py:36‑38].

- [1] UNVERIFIED encoding.py:36-36

**Grade:** correct – cites short paths, so those are unverified

## Q5 · qwen/qwen3.8-27b
**How does it support rotating to a new secret key while old keys still work?**

It supports key rotation by storing multiple keys in a list and using different keys for signing versus verification.

**Storage**
Both `Signer` and `Serializer` accept a single key or an iterable of keys. The helper `_make_keys_list` normalizes the input into a `list[bytes]` [1](cite:1). This list is stored as `self.secret_keys` in both classes [src/itsdangerous/signer.py:138-143, src/itsdangerous/serializer.py:203-208]. The docstring states the list is ordered "from oldest to newest" and that "the newest (last) key is used for signing" [2](cite:2).

**Signing**
When deriving the key for a new signature, `derive_key` defaults to `self.secret_keys[-1]` (the newest key) if no specific key is passed [3](cite:3). The `secret_key` property also returns `self.secret_keys[-1]` for backward compatibility [src/itsdangerous/signer.py:175-180, src/itsdangerous/serializer.py:236-241].

**Verification**
The provided files do not show the verification loop that iterates over all `secret_keys` to find a match. However, the design implies that verification tries each key in the list (typically from newest to oldest or all of them) so that tokens signed with older keys remain valid until those keys are removed from the list. The docstring explicitly notes this allows "a key rotation system to keep a list of allowed keys and remove expired ones" [4](cite:4).

**Summary**
To rotate keys, you append the new key to the end of the `secret_keys` list. New signatures use the last key, while old signatures can still be verified because the older keys remain in the list. You can remove old keys once you no longer need to verify tokens signed with them.

- [1] ok src/itsdangerous/signer.py:67-73
- [2] ok src/itsdangerous/signer.py:138-142
- [3] ok src/itsdangerous/signer.py:195-196
- [4] ok src/itsdangerous/signer.py:141-142

**Grade:** partial – honestly says the verification loop isn't in the context, then speculates

## Q5 · openai/gpt-oss-120b
**How does it support rotating to a new secret key while old keys still work?**

The classes keep **all allowed keys in a list** and always use the newest one for creating new signatures while still accepting any of the older keys when verifying.

* In both `Signer` and `Serializer` the constructor builds a list of keys from the supplied `secret_key` argument:  

  * `self.secret_keys: list[bytes] = _make_keys_list(secret_key)` [signer.py:138‑144] and  
  * `self.secret_keys: list[bytes] = _make_keys_list(secret_key)` [serializer.py:203‑209].

* The doc‑string comments explain the ordering:  

  * “The list of secret keys to try for verifying signatures, from oldest to newest. The newest (last) key is used for signing.” [signer.py:138‑143] and the same comment in `serializer.py` [serializer.py:203‑207].

* The `secret_key` property returns the **last entry** (the newest key):  

  * `return self.secret_keys[-1]` [signer.py:177‑180] and  
  * `return self.secret_keys[-1]` [serializer.py:236‑241].

* When deriving a key for signing, if no explicit `secret_key` is passed, the method falls back to the last key in the list:  

  * `if secret_key is None: secret_key = self.secret_keys[-1]` [signer.py:195‑197].

Thus, to rotate keys you supply a list of keys (old ones first, new one last). The system will sign with the newest key but will still verify signatures created with any of the older keys because verification iterates over `self.secret_keys`. This design enables seamless key rotation while maintaining compatibility with existing signatures.


**Grade:** partial – states the verification loop as fact with no supporting context

## Q6 · qwen/qwen3.8-27b
**What happens when a value signed with one salt is unsigned with a different salt?**

When a value signed with one salt is unsigned with a different salt, the signature verification fails and a `BadSignature` exception is raised.

Here's the flow:

1. **Key derivation differs**: The `Signer` derives its signing key from both the `secret_key` and `salt` (via `key_derivation`, defaulting to `django-concat`) [src/itsdangerous/signer.py:87-93, 122-127]. A different salt produces a different derived key.

2. **Signature mismatch**: In `verify_signature`, the derived key is used to check the HMAC signature against the value [1](cite:1). Since the key differs from the one used during signing, `self.algorithm.verify_signature(key, value, sig)` returns `False` for all secret keys, and the method returns `False` [2](cite:2).

3. **Exception raised**: Back in `unsign`, because `verify_signature` returns `False`, the method raises `BadSignature(f"Signature {sig!r} does not match", payload=value)` [3](cite:3).

4. **Serializer level**: If using `Serializer.loads`, it iterates over unsigners and catches `BadSignature` [4](cite:4). If no signer succeeds, it re-raises the last `BadSignature` [5](cite:5).

In short: different salt → different derived key → signature check fails → `BadSignature` is raised.

- [1] ok src/itsdangerous/signer.py:236-240
- [2] ok src/itsdangerous/signer.py:242-242
- [3] ok src/itsdangerous/signer.py:253-256
- [4] ok src/itsdangerous/serializer.py:337-341
- [5] ok src/itsdangerous/serializer.py:343-343

**Grade:** correct

## Q6 · openai/gpt-oss-120b
**What happens when a value signed with one salt is unsigned with a different salt?**

When the signed data is verified with a **different salt**, the signature check fails and a `BadSignature` exception is raised.

* `Signer.unsign()` splits the value and calls `verify_signature()`. If the verification returns `False` it raises `BadSignature` [src/itsdangerous/signer.py:251‑256].
* `verify_signature()` tries to decode the signature and then checks it against each secret key. Because the salt used to create the signer is different, the derived signing key is different, so the check returns `False` [src/itsdangerous/signer.py:227‑242].
* The `Serializer.loads()` method catches `BadSignature` from each signer and finally re‑raises the last one if none succeed [src/itsdangerous/serializer.py:337‑343].

Thus, unsigned with a different salt results in a `BadSignature` error.


**Grade:** correct

## Q7 · qwen/qwen3.8-27b
**Which exception is raised when a timed signature is too old, and what does it carry?**

When a timed signature is older than the allowed `max_age`, the `SignatureExpired` exception is raised.

- **Class hierarchy:** `SignatureExpired` is a subclass of `BadTimeSignature`, which is itself a subclass of `BadSignature` [src/itsdangerous/exc.py:60-63, 36-39].
- **What it carries:** Because it inherits from `BadTimeSignature`, it carries:
  - `message` and `payload` (inherited from `BadSignature` via `super().__init__`) [1](cite:1).
  - `date_signed`: a timezone-aware `datetime` (or `None`) indicating when the signature was created, useful for telling users how long a link has been stale [2](cite:2).

**Where it is raised:**
- `TimestampSigner.unsign` raises `SignatureExpired` when the signature is expired [3](cite:3).
- `TimedSerializer.loads` propagates `SignatureExpired` without trying the next signer [4](cite:4).
- `TimestampSigner.validate` catches `BadSignature` (which includes `SignatureExpired`) and returns `False` [5](cite:5).

- [1] ok src/itsdangerous/exc.py:41-47
- [2] ok src/itsdangerous/exc.py:49-57
- [3] ok src/itsdangerous/timed.py:22-27
- [4] ok src/itsdangerous/timed.py:213-216
- [5] ok src/itsdangerous/timed.py:160-167

**Grade:** correct

## Q7 · openai/gpt-oss-120b
**Which exception is raised when a timed signature is too old, and what does it carry?**

The timed serializer raises **`SignatureExpired`** when a timestamped signature is older than the allowed `max_age`.  

* `SignatureExpired` is defined as a subclass of `BadTimeSignature` [src/itsdangerous/exc.py:60‑63].  
* `BadTimeSignature` (its parent) stores the time the signature was created in the attribute `date_signed` [src/itsdangerous/exc.py:36‑57].  

Thus, when a timed signature is too old, a `SignatureExpired` exception is raised and it carries the `date_signed` datetime indicating when the signature was originally generated.


**Grade:** partial – omits payload and the message

## Q8 · qwen/qwen3.8-27b
**How does itsdangerous encrypt the payload with AES?**

The provided files do not contain any AES encryption logic. ItsDangerous does not encrypt payloads; it cryptographically **signs** them to ensure integrity, as stated in the README: "Data is cryptographically signed to ensure that a token has not been tampered with" [1](cite:1).

The payload handling shown in the code involves serialization and encoding, not encryption:

1.  **Serialization**: The `dump_payload` method serializes the object and converts it to bytes using `want_bytes` [2](cite:2).
2.  **Deserialization**: The `load_payload` method deserializes the bytes, decoding from UTF-8 if the serializer is text-based [3](cite:3).
3.  **Encoding**: The `encoding` module provides `base64_encode` and `base64_decode` functions, which are used for encoding the signed data, not for encryption [4](cite:4).
4.  **Signing**: The `signer` module imports `hmac` and `hashlib`, indicating that HMAC-based signing is used to verify the payload's authenticity [5](cite:5).

There is no mention of AES, `cryptography`, or any encryption algorithm in the provided file contents.

- [1] ok README.md:8-9
- [2] ok src/itsdangerous/serializer.py:271-276
- [3] ok src/itsdangerous/serializer.py:243-269
- [4] ok src/itsdangerous/encoding.py:1-8
- [5] ok src/itsdangerous/signer.py:1-12

**Grade:** correct – says it's not in the files

## Q8 · openai/gpt-oss-120b
**How does itsdangerous encrypt the payload with AES?**

The repository does not contain any implementation that encrypts a payload with AES. All of the source files shown relate to signing, base‑64 encoding, JSON (or other) serialization, and optional timestamp handling, but none import or use an AES cipher or any symmetric‑encryption library. Therefore, itsdangerous does not encrypt payloads with AES in the provided code.


**Grade:** correct – says it's not in the files
