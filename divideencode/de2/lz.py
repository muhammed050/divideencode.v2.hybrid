"""DE2 LZ/TSE core (M1/M2): the heart of V2/V3.

v3 matcher (branch v3-strong-core), format-compatible with the V2 frame:
- multiplicative integer hash over 4-byte windows; flat head table +
  prev-chain arrays replace the V2 dict-of-lists (no per-position bytes
  slicing, no list append/trim churn)
- bounded chain walk: max_chain depth, nice_len early exit, good_len
  chain acceleration
- holdback lazy parsing: the pending match is re-evaluated against the
  next position's candidate with an explicit cost rule, so each position
  is searched exactly once (the V2 engine searched twice per match)
- REP0..3 candidates checked before every chain walk and preferred on
  length ties against explicit distances (a rep symbol codes cheaper)
- explicit deterministic levels: FAST / BALANCED / MAX

Frame layout (unchanged, see decode()):
    varint num_matches, varint literal_count,
    entropy stream(literals),
    varint len + entropy stream(literal lengths),
    varint len + entropy stream(match lengths, value = len - MIN_MATCH),
    varint len + entropy stream(distances: 0..3 = rep index, >=4 -> d - 3)

The decoder is a flat iterative state machine: strict bounds checks,
overlap-safe copies, exact stream accounting, no recursion.
"""
from array import array

from ..bitstream import encode_varint as _wv, decode_varint as _rv
from ..errors import CorruptedError
from . import entropy

MIN_MATCH = 4
DEFAULT_WINDOW = 262144          # 256 KiB
MAX_CHAIN = 32                   # BALANCED probing bound (legacy default)
LAZY = True                      # legacy knob kept for API compatibility
CHAIN_HARD_LIMIT = 256           # legacy constant, unused by the v3 encoder

M32 = 0xFFFFFFFF
_KNUTH = 0x9E3779B1              # multiplicative hash constant

# shared encoder/decoder REP0..3 initial distances (MRU order).
# WARNING: both sides MUST use this exact tuple or rep-coded streams
# decode to wrong data (the format has no field to renegotiate it).
REP_INIT = (1, 2, 4, 8)

_LIT_COST = 4                    # literal bits proxy for distance-bias rule

# level -> knobs; budget_floor bounds the adaptive probe budget
# (floor == max_chain disables shrinking: BALANCED/MAX always search deep);
# insert_shift doubles the interior-match hash-insertion stride
_LEVEL_FAST = dict(max_chain=6, lazy=False, nice_len=24, good_len=8,
                   insert_step=3, budget_floor=2, insert_shift=0)
_LEVEL_BALANCED = dict(max_chain=32, lazy=True, nice_len=96, good_len=24,
                       insert_step=0, budget_floor=32, insert_shift=0)
_LEVEL_MAX = dict(max_chain=512, lazy=True, nice_len=4096, good_len=128,
                  insert_step=0, budget_floor=512, insert_shift=0)
LEVELS = {"FAST": _LEVEL_FAST, "BALANCED": _LEVEL_BALANCED,
          "MAX": _LEVEL_MAX}


def _match_length(data, a, b, limit):
    """Length of common prefix of data[a:] and data[b:], capped at limit."""
    l = 0
    while l + 8 <= limit and data[a + l:a + l + 8] == data[b + l:b + l + 8]:
        l += 8
    while l < limit and data[a + l] == data[b + l]:
        l += 1
    return l


def encode(data, window=DEFAULT_WINDOW, max_chain=MAX_CHAIN, lazy=LAZY,
           level=None):
    """bytes -> DE2 LZ frame v1 (separated streams, see module docstring).

    level: "FAST" | "BALANCED" | "MAX". Explicit max_chain/lazy kwargs
    override the level table (legacy API preserved).
    """
    num_matches, literals, ll_out, ml_out, dist_out = _tokenize(
        data, window=window, max_chain=max_chain, lazy=lazy, level=level)
    return _frame(num_matches, literals, ll_out, ml_out, dist_out)


def _tokenize(data, window=DEFAULT_WINDOW, max_chain=MAX_CHAIN, lazy=LAZY,
              level=None):
    """Shared tokenizer: bytes -> (num_matches, literals, ll, ml, dist)."""
    if level is not None:
        try:
            cfg = LEVELS[level]
        except KeyError:
            raise ValueError("unknown LZ level %r" % (level,))
        max_chain = cfg["max_chain"]
        lazy = cfg["lazy"]
    else:
        # legacy explicit knobs win over the table; defaults mean BALANCED
        cfg = LEVELS["BALANCED"]
    nice_len = cfg["nice_len"]
    good_len = cfg["good_len"]
    forced_step = cfg["insert_step"]
    ins_shift = cfg["insert_shift"]
    budget_floor = cfg["budget_floor"]

    n = len(data)
    literals = bytearray()
    ll_out = bytearray()
    ml_out = bytearray()
    dist_out = bytearray()
    num_matches = 0
    r0, r1, r2, r3 = REP_INIT     # rep0..rep3 distances (MRU)
    nm = MIN_MATCH

    if n == 0:
        return (num_matches, literals, ll_out, ml_out, dist_out)

    # ---- hash structures: flat head table + prev chain array ----
    hb = n.bit_length()
    if hb < 12:
        hb = 12
    elif hb > 20:
        hb = 20
    hshift = 32 - hb
    head = [-1] * (1 << hb)
    prev = array("i", b"\xff\xff\xff\xff") * n   # all -1
    fb4 = int.from_bytes

    i = 0
    lit_start = 0
    ins_upto = 0                 # first position not yet hash-inserted
    pend_pos = -1                # held-back match awaiting comparison
    pend_len = 0
    pend_dist = 0
    pend_rep = -1
    budget = max_chain           # adaptive probe budget (local repetitiveness)
    key = -1                     # rolling 4-byte key; -1 = needs resync
    seq_adv = False              # previous advance was a sequential i += 1

    while i < n:
        best_len = 0
        best_dist = 0
        best_rep = -1
        limit = n - i

        # ---- repeat-offset candidates (cheap, checked first) ----
        di = data[i]
        d = r0
        if d <= i and data[i - d] == di:
            l = _match_length(data, i - d, i, limit)
            best_len = l
            best_dist = d
            best_rep = 0
        d = r1
        if d <= i and data[i - d] == di:
            l = _match_length(data, i - d, i, limit)
            if l > best_len:
                best_len = l
                best_dist = d
                best_rep = 1
        d = r2
        if d <= i and data[i - d] == di:
            l = _match_length(data, i - d, i, limit)
            if l > best_len:
                best_len = l
                best_dist = d
                best_rep = 2
        d = r3
        if d <= i and data[i - d] == di:
            l = _match_length(data, i - d, i, limit)
            if l > best_len:
                best_len = l
                best_dist = d
                best_rep = 3

        # ---- hash-chain candidates ----
        h = -1
        keyable = i + nm <= n
        if keyable:
            if key < 0 or not seq_adv:
                key = fb4(data[i:i + nm], "little")
            else:
                # keep little-endian layout: drop low byte, append high
                key = ((key >> 8) | (data[i + nm - 1] << 24)) & M32
            if best_len < nice_len:
                h = (key * _KNUTH & M32) >> hshift
                pos = head[h]
                if best_len >= good_len:
                    depth = max_chain >> 2
                elif budget < max_chain:
                    depth = budget
                else:
                    depth = max_chain
                bl = best_len
                bd = 0
                low_i = i - window
                while pos >= 0 and depth > 0:
                    if pos < low_i:
                        break
                    depth -= 1
                    if bl < limit and data[pos + bl] == data[i + bl]:
                        l = _match_length(data, pos, i, limit)
                        if l > bl:
                            nd = i - pos
                            # v2-aware acceptance: a farther candidate must
                            # buy back its extra distance-class bits with
                            # literal savings (MRU chains yield near-first,
                            # so this prunes exactly the losing tail)
                            if bl == 0 or \
                                    nd.bit_length() - bd.bit_length() <= \
                                    (l - bl) * _LIT_COST:
                                bl = l
                                bd = nd
                                if l >= nice_len or l >= limit:
                                    break
                    pos = prev[pos]
                if bl > best_len:
                    best_len = bl
                    best_dist = bd
                    best_rep = -1

        # ---- adaptive probe budget from observed match yield ----
        if best_len >= 16:
            budget >>= 1
            if budget < budget_floor:
                budget = budget_floor
        elif best_len < nm:
            budget += 2
            if budget > max_chain:
                budget = max_chain

        # ---- hash insertion of the current position ----
        if keyable:
            if h < 0:      # search was skipped (rep already at nice_len)
                h = (key * _KNUTH & M32) >> hshift
            if i >= ins_upto:
                prev[i] = head[h]
                head[h] = i
                ins_upto = i + 1

        # ---- parse decision (holdback lazy) ----
        if pend_pos < 0:
            if best_len >= nm:
                pend_pos = i
                pend_len = best_len
                pend_dist = best_dist
                pend_rep = best_rep
            i += 1
            seq_adv = True
            continue

        # candidate at i competes with held match at pend_pos
        take_new = best_len > pend_len
        if lazy and not take_new and best_rep >= 0 and \
                best_len == pend_len and pend_rep < 0:
            take_new = True   # equal length, rep-coded: cheaper symbol
        if take_new:
            # held position falls into the literal run; hold new candidate
            pend_pos = i
            pend_len = best_len
            pend_dist = best_dist
            pend_rep = best_rep
            i += 1
            seq_adv = True
            continue

        # ---- emit the held match ----
        p = pend_pos
        L = pend_len
        literals += data[lit_start:p]
        ll_out += _wv(p - lit_start)
        ml_out += _wv(L - nm)
        if pend_rep == 0:
            dist_out.append(0)
        elif pend_rep == 1:
            dist_out.append(1)
            r1, r0 = r0, r1
        elif pend_rep == 2:
            dist_out.append(2)
            r2, r1, r0 = r1, r0, r2
        elif pend_rep == 3:
            dist_out.append(3)
            r3, r2, r1, r0 = r2, r1, r0, r3
        else:
            dist_out += _wv(pend_dist + 3)
            r3, r2, r1, r0 = r2, r1, r0, pend_dist
        num_matches += 1
        # index covered interior positions (sparse on long matches)
        stop = p + L
        end_ins = n - nm + 1
        if stop < end_ins:
            end_ins = stop
        step = forced_step
        if not step:
            step = (1 if L <= 16 else (2 if L <= 64 else 4)) << ins_shift
        j = p + 1
        if j < ins_upto:
            j += ((ins_upto - j + step - 1) // step) * step
        while j < end_ins:
            hj = (fb4(data[j:j + nm], "little") * _KNUTH & M32) >> hshift
            prev[j] = head[hj]
            head[hj] = j
            j += step
        if ins_upto < stop:
            ins_upto = stop
        lit_start = stop
        pend_pos = -1
        i = stop
        seq_adv = False

    literals += data[lit_start:]

    return (num_matches, literals, ll_out, ml_out, dist_out)


def _frame(num_matches, literals, ll_out, ml_out, dist_out):
    frame = bytearray()
    frame += _wv(num_matches)
    frame += _wv(len(literals))
    frame += entropy.encode_stream(bytes(literals))
    frame += _wv(len(ll_out))
    frame += entropy.encode_stream(bytes(ll_out))
    frame += _wv(len(ml_out))
    frame += entropy.encode_stream(bytes(ml_out))
    frame += _wv(len(dist_out))
    frame += entropy.encode_stream(bytes(dist_out))
    return bytes(frame)


# ------------------------------------------------------------ v2 frames ---
# Distance alphabet (structured, deflate/zstd-style):
#     symbol 0..3   -> rep0..rep3, no extra bits
#     symbol s>=4   -> explicit distance d: nb = s - 3 is the bit length
#                      of d (nb >= 1); the low (nb - 1) bits of d follow
#                      as extra bits (leading bit implied).
# Symbols are Huffman-coded in their own stream; extra bits accumulate
# MSB-first into a separate byte slice. A 2-byte varint (<= 14 info bits)
# becomes ~7-9 coded bits for typical mid-range distances.

def _dist_split(dists_bytes):
    """v1 dist varint bytes -> (dsym bytes, extra-bits bytes)."""
    dsyms = bytearray()
    xbits = bytearray()
    cur = 0
    nbits = 0
    p = 0
    endn = len(dists_bytes)
    while p < endn:
        e, p = _rv(dists_bytes, p, endn)
        if e <= 3:
            dsyms.append(e)
            continue
        d = e - 3                     # explicit distance, d >= 1
        nb = d.bit_length()
        dsyms.append(nb + 3)
        if nb > 1:
            cur = (cur << (nb - 1)) | (d & ((1 << (nb - 1)) - 1))
            nbits += nb - 1
            while nbits >= 8:
                nbits -= 8
                xbits.append((cur >> nbits) & 0xFF)
            cur &= (1 << nbits) - 1
    if nbits:
        xbits.append((cur << (8 - nbits)) & 0xFF)
    return bytes(dsyms), bytes(xbits)


def encode_v2(data, window=DEFAULT_WINDOW, max_chain=MAX_CHAIN, lazy=LAZY,
              level=None):
    """v2 frame: same tokenizer, structured distance coding."""
    nm, literals, ll_raw, ml_raw, dist_raw = _tokenize(
        data, window=window, max_chain=max_chain, lazy=lazy, level=level)
    dsyms, xbits = _dist_split(bytes(dist_raw))

    out = bytearray()
    out += _wv(nm)
    out += _wv(len(literals))
    out += entropy.encode_stream(bytes(literals))
    out += _wv(len(ll_raw))
    out += entropy.encode_stream(bytes(ll_raw))
    out += _wv(len(ml_raw))
    out += entropy.encode_stream(bytes(ml_raw))
    out += _wv(len(dsyms))
    out += entropy.encode_stream(dsyms)
    out += _wv(len(xbits))
    out += xbits
    return bytes(out)


def decode_v2(blob, pos, end, raw_len, tables):
    """Decode a v2 LZ frame. Returns (data, new_pos)."""
    num_matches, pos = _rv(blob, pos, end)
    lit_count, pos = _rv(blob, pos, end)
    literals, pos = entropy.decode_stream(blob, pos, end, lit_count, tables)

    ll_buf = ml_buf = ds_buf = None
    for target in range(3):
        slen, pos = _rv(blob, pos, end)
        sblob, pos = entropy.decode_stream(blob, pos, end, slen, tables)
        if target == 0:
            ll_buf, ll_end = sblob, slen
        elif target == 1:
            ml_buf, ml_end = sblob, slen
        else:
            ds_buf, ds_end = sblob, slen
    xlen, pos = _rv(blob, pos, end)
    if xlen > end - pos:
        raise CorruptedError("lz extra-bits truncated")
    x_end = pos + xlen
    if x_end != end:
        raise CorruptedError("lz frame has excess data")

    out = bytearray()
    r0, r1, r2, r3 = REP_INIT
    li = 0
    p_ll = p_ml = p_ds = 0
    xp = pos                       # cursor into extra-bits region
    acc = 0                        # MSB-first extra-bit accumulator
    nacc = 0

    for _ in range(num_matches):
        # literal length varint (inline, 1-byte fast path)
        if p_ll < ll_end:
            v = ll_buf[p_ll]
            p_ll += 1
            if v > 127:
                v &= 127
                shift = 7
                while True:
                    if p_ll >= ll_end:
                        raise CorruptedError("truncated varint")
                    b = ll_buf[p_ll]
                    p_ll += 1
                    v |= (b & 127) << shift
                    if b < 128:
                        break
                    shift += 7
                    if shift > 56:
                        raise CorruptedError("varint overflow")
            ll = v
        else:
            raise CorruptedError("truncated literal-length stream")
        # match length varint
        if p_ml < ml_end:
            v = ml_buf[p_ml]
            p_ml += 1
            if v > 127:
                v &= 127
                shift = 7
                while True:
                    if p_ml >= ml_end:
                        raise CorruptedError("truncated varint")
                    b = ml_buf[p_ml]
                    p_ml += 1
                    v |= (b & 127) << shift
                    if b < 128:
                        break
                    shift += 7
                    if shift > 56:
                        raise CorruptedError("varint overflow")
            ml = v + MIN_MATCH
        else:
            raise CorruptedError("truncated match-length stream")
        # distance symbol
        if p_ds < ds_end:
            s = ds_buf[p_ds]
            p_ds += 1
        else:
            raise CorruptedError("truncated distance-symbol stream")

        if ll:
            if li + ll > lit_count:
                raise CorruptedError("lz literal run exceeds pool")
            out += literals[li:li + ll]
            li += ll
        olen = len(out)

        if s <= 3:
            if s == 0:
                d = r0
            elif s == 1:
                d = r1
                r1, r0 = r0, r1
            elif s == 2:
                d = r2
                r2, r1, r0 = r1, r0, r2
            else:
                d = r3
                r3, r2, r1, r0 = r2, r1, r0, r3
            if d < 1 or d > olen:
                raise CorruptedError("lz invalid repeat distance")
        else:
            nb = s - 3
            if nb < 1 or nb > 25:
                raise CorruptedError("lz invalid distance symbol")
            extra = nb - 1
            if extra:
                while nacc < extra:
                    if xp >= x_end:
                        raise CorruptedError("lz extra bits exhausted")
                    acc = (acc << 8) | blob[xp]
                    xp += 1
                    nacc += 8
                d = ((1 << (nb - 1)) |
                     ((acc >> (nacc - extra)) & ((1 << extra) - 1)))
                nacc -= extra
                acc &= (1 << nacc) - 1
            else:
                d = 1
            if d > olen:
                raise CorruptedError("lz invalid distance")
            r3, r2, r1, r0 = r2, r1, r0, d

        if olen + ml > raw_len:
            raise CorruptedError("lz overrun of block size")
        src = olen - d
        if d >= ml:
            out += out[src:src + ml]
        else:
            # overlap-safe exponential copy: O(log ml) appends
            while True:
                chunk = d if d < ml else ml
                out += out[len(out) - d:len(out) - d + chunk]
                ml -= chunk
                if ml <= 0:
                    break
                d += d

    if li > lit_count:
        raise CorruptedError("lz literal pool not fully consumed")
    if p_ll != ll_end or p_ml != ml_end or p_ds != ds_end:
        raise CorruptedError("lz stream has unconsumed bytes")
    if xp != x_end and num_matches:
        raise CorruptedError("lz extra bits not fully consumed")
    out += literals[li:]
    if len(out) != raw_len:
        raise CorruptedError("lz produced wrong block size")
    return bytes(out), pos


def decode(blob, pos, end, raw_len, tables):
    """Decode an LZ frame. Returns (data, new_pos)."""
    num_matches, pos = _rv(blob, pos, end)
    lit_count, pos = _rv(blob, pos, end)
    literals, pos = entropy.decode_stream(blob, pos, end, lit_count, tables)

    ll_buf, ml_buf, d_buf = None, None, None
    for target in range(3):
        slen, pos = _rv(blob, pos, end)
        sblob, pos = entropy.decode_stream(blob, pos, end, slen, tables)
        if target == 0:
            ll_buf = sblob
            ll_end = slen
        elif target == 1:
            ml_buf = sblob
            ml_end = slen
        else:
            d_buf = sblob
            d_end = slen
    if pos != end:
        raise CorruptedError("lz frame has excess data")

    out = bytearray()
    r0, r1, r2, r3 = REP_INIT
    li = 0
    p_ll = p_ml = p_d = 0
    for _ in range(num_matches):
        # ---- inline varints (single-byte fast path) ----
        if p_ll < ll_end:
            v = ll_buf[p_ll]
            p_ll += 1
            if v > 127:
                v &= 127
                shift = 7
                while True:
                    if p_ll >= ll_end:
                        raise CorruptedError("truncated varint")
                    b = ll_buf[p_ll]
                    p_ll += 1
                    v |= (b & 127) << shift
                    if b < 128:
                        break
                    shift += 7
                    if shift > 56:
                        raise CorruptedError("varint overflow")
            ll = v
        else:
            raise CorruptedError("truncated literal-length stream")
        if p_ml < ml_end:
            v = ml_buf[p_ml]
            p_ml += 1
            if v > 127:
                v &= 127
                shift = 7
                while True:
                    if p_ml >= ml_end:
                        raise CorruptedError("truncated varint")
                    b = ml_buf[p_ml]
                    p_ml += 1
                    v |= (b & 127) << shift
                    if b < 128:
                        break
                    shift += 7
                    if shift > 56:
                        raise CorruptedError("varint overflow")
            ml = v + MIN_MATCH
        else:
            raise CorruptedError("truncated match-length stream")
        if p_d < d_end:
            e = d_buf[p_d]
            p_d += 1
            if e > 127:
                e &= 127
                shift = 7
                while True:
                    if p_d >= d_end:
                        raise CorruptedError("truncated varint")
                    b = d_buf[p_d]
                    p_d += 1
                    e |= (b & 127) << shift
                    if b < 128:
                        break
                    shift += 7
                    if shift > 56:
                        raise CorruptedError("varint overflow")
        else:
            raise CorruptedError("truncated distance stream")

        # ---- execute token ----
        if ll:
            if li + ll > lit_count:
                raise CorruptedError("lz literal run exceeds pool")
            out += literals[li:li + ll]
            li += ll
        olen = len(out)
        if e <= 3:
            if e == 0:
                d = r0
            elif e == 1:
                d = r1
                r1, r0 = r0, r1
            elif e == 2:
                d = r2
                r2, r1, r0 = r1, r0, r2
            else:
                d = r3
                r3, r2, r1, r0 = r2, r1, r0, r3
            if d < 1 or d > olen:
                raise CorruptedError("lz invalid repeat distance")
        else:
            d = e - 3
            if d < 1 or d > olen:
                raise CorruptedError("lz invalid distance")
            r3, r2, r1, r0 = r2, r1, r0, d
        if olen + ml > raw_len:
            raise CorruptedError("lz overrun of block size")
        src = olen - d
        if d >= ml:
            out += out[src:src + ml]
        else:
            # overlap-safe exponential copy: O(log ml) appends
            while True:
                chunk = d if d < ml else ml
                out += out[len(out) - d:len(out) - d + chunk]
                ml -= chunk
                if ml <= 0:
                    break
                d += d

    if li > lit_count:
        raise CorruptedError("lz literal pool not fully consumed")
    if p_ll != ll_end or p_ml != ml_end or p_d != d_end:
        raise CorruptedError("lz stream has unconsumed bytes")
    out += literals[li:]
    if len(out) != raw_len:
        raise CorruptedError("lz produced wrong block size")
    return bytes(out), pos
