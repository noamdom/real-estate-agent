# Pinecone Data Generation Prompt — v1

Paste the prompt below directly into an LLM (GPT-4o, Claude Opus, or equivalent).
Generate in batches of 100 and concatenate — most models hit output limits above that.

---

## PROMPT (copy everything below this line)

You are a real estate data generator for an Israeli property market database.
Generate exactly **100 realistic Israeli property transaction records** as a valid JSON array.
Each element represents one past property sale and will be stored in a Pinecone vector database
to serve as comparable listings (comps) for an AI property triage system.

---

### Output format

Return ONLY a raw JSON array — no markdown, no explanation, no code fences.
Each object must have exactly these fields:

```
id                string    unique identifier, format "comp-NNNNN" (5 digits, zero-padded, sequential from the batch start)
property_type     string    see allowed values below
city              string    see allowed cities below
neighborhood      string    neighborhood within the city
location          string    "{neighborhood}, {city}"
size_sqm          number    float, property size in square metres
num_rooms         integer   Israeli room count (includes living room)
floor_number      integer   floor the unit is on (0 = ground)
has_parking       boolean
has_balcony       boolean
building_year     integer   year the building was constructed
condition         string    see allowed values below
price_listed      number    original asking price in NIS (integer)
price_sold        number    final sale price in NIS (integer, always <= price_listed)
price_per_sqm     number    round(price_sold / size_sqm) — compute this exactly
days_on_market    integer   days between first listing and signed contract
sale_date         string    ISO date "YYYY-MM-DD", between 2023-01-01 and 2025-06-01
embed_text        string    exactly: "{property_type}, {num_rooms} rooms, {size_sqm}sqm, {condition}, {neighborhood}, {city}"
```

---

### Allowed values

**property_type** (distribution across 1000 total records):
- `apartment`   — 55 %
- `villa`       — 10 %
- `penthouse`   —  8 %
- `duplex`      —  5 %
- `studio`      —  5 %
- `office`      —  8 %
- `retail`      —  5 %
- `commercial`  —  4 %

**condition**:
- `new`               — brand new, never lived in
- `renovated`         — fully renovated in last 5 years
- `good`              — well maintained, no major works needed
- `fair`              — functional but needs cosmetic work
- `poor`              — requires significant renovation

**condition distribution**: new 10%, renovated 25%, good 35%, fair 20%, poor 10%

---

### Cities, neighborhoods, and realistic price ranges

Use only cities and neighborhoods from this list.
Price per sqm (NIS) is for apartments — scale for other types (see below).

| City | Neighborhoods | Price/sqm range (NIS) |
|---|---|---|
| Tel Aviv | Florentin, Rothschild, Dizengoff, Old North, Neve Tzedek, Jaffa, Ramat Aviv, Tel Aviv Port, Lev HaIr | 40,000 – 85,000 |
| Jerusalem | German Colony, Rehavia, Katamon, Baka, Talpiot, Ramat Eshkol, Musrara, Ein Kerem | 25,000 – 55,000 |
| Haifa | Hadar, Carmel, German Colony Haifa, Bat Galim, Merkaz HaCarmel, Neve Sha'anan | 12,000 – 28,000 |
| Herzliya | Herzliya Pituach, Herzliya Center, Neve Amirim | 28,000 – 65,000 |
| Ra'anana | Ra'anana Center, Neve Zemer, Kiryat Wolfson | 20,000 – 35,000 |
| Netanya | Old City Netanya, Ir Yamim, Poleg, Kiryat Hasharon | 14,000 – 28,000 |
| Beer Sheva | Old City Beer Sheva, Ramot, Dalet, Gimel | 7,000 – 14,000 |
| Ramat Gan | Diamond Exchange District, Kiryat Krinitzi, Neve Efal | 22,000 – 42,000 |
| Ashdod | Lamed, Yod Alef, Hey, Dalet | 10,000 – 18,000 |
| Petah Tikva | Center, Kiryat Matalon, Neve Efraim | 12,000 – 22,000 |
| Rishon LeZion | Center, Nahalat Yehuda, Ramat Eliyahu | 13,000 – 22,000 |
| Modi'in | Buchman, Moriah, Ganim | 16,000 – 26,000 |
| Kfar Saba | Center, Neve Yaraq | 18,000 – 30,000 |
| Givatayim | Center, Borochov | 28,000 – 45,000 |

**City distribution across 1000 records**:
Tel Aviv 22%, Jerusalem 14%, Haifa 10%, Herzliya 7%, Ra'anana 5%,
Netanya 7%, Beer Sheva 5%, Ramat Gan 8%, Ashdod 5%, Petah Tikva 5%,
Rishon LeZion 5%, Modi'in 4%, Kfar Saba 2%, Givatayim 1%

---

### Size and room count by property type

| property_type | size_sqm range | num_rooms range |
|---|---|---|
| studio | 28 – 45 | 1 |
| apartment | 45 – 160 | 2 – 5 |
| duplex | 100 – 200 | 4 – 7 |
| penthouse | 120 – 300 | 4 – 8 |
| villa | 180 – 550 | 5 – 10 |
| office | 40 – 400 | 0 (set num_rooms to 0 for commercial) |
| retail | 30 – 250 | 0 |
| commercial | 50 – 500 | 0 |

---

### Price scaling by property type

Base price/sqm comes from the city table (apartment rate).
Apply these multipliers for other types:

| property_type | multiplier |
|---|---|
| studio | 0.95 |
| apartment | 1.00 |
| duplex | 1.05 |
| penthouse | 1.35 |
| villa | 0.80 (large sqm offsets the premium) |
| office | 0.75 |
| retail | 0.85 |
| commercial | 0.70 |

---

### Condition adjustments to price/sqm

| condition | price adjustment |
|---|---|
| new | + 15 % |
| renovated | + 8 % |
| good | + 0 % (baseline) |
| fair | − 8 % |
| poor | − 18 % |

---

### Negotiation delta (price_sold vs price_listed)

- `new` condition: discount 0 – 2 %
- `renovated`: discount 1 – 5 %
- `good`: discount 2 – 7 %
- `fair`: discount 4 – 10 %
- `poor`: discount 7 – 18 %

price_sold = round(price_listed × (1 − discount))

---

### Days on market

| condition | days_on_market range |
|---|---|
| new | 7 – 30 |
| renovated | 10 – 45 |
| good | 14 – 60 |
| fair | 30 – 120 |
| poor | 45 – 180 |

High-demand cities (Tel Aviv, Herzliya, Givatayim) — use the lower half of the range.
Low-demand cities (Beer Sheva, Ashdod) — use the upper half.

---

### Other field rules

- `floor_number`: studios and apartments 0–15; penthouses always top floor (8–20); villas always 0; offices 0–20
- `has_parking`: true for 70% of records; always true for villas and penthouses
- `has_balcony`: true for 65% of records; always false for offices/retail/commercial
- `building_year`: range 1960–2024; new condition → 2020–2024; poor condition → 1960–1985
- `sale_date`: spread evenly across 2023-01-01 to 2025-06-01
- `price_per_sqm`: must be computed as `round(price_sold / size_sqm)` — do not approximate
- `embed_text`: must be exactly `"{property_type}, {num_rooms} rooms, {size_sqm}sqm, {condition}, {neighborhood}, {city}"` — for commercial types where num_rooms=0 use `"0 rooms"`

---

### Quality checks (apply before returning)

- No `price_sold` may exceed `price_listed`
- No `price_per_sqm` below 5,000 or above 100,000
- No `size_sqm` below 25 or above 600
- `embed_text` must exactly match the template — no extra words
- All IDs must be unique within the batch
- `sale_date` must be a valid calendar date

---

### Example record

```json
{
  "id": "comp-00001",
  "property_type": "apartment",
  "city": "Tel Aviv",
  "neighborhood": "Florentin",
  "location": "Florentin, Tel Aviv",
  "size_sqm": 82.0,
  "num_rooms": 3,
  "floor_number": 3,
  "has_parking": false,
  "has_balcony": true,
  "building_year": 1985,
  "condition": "renovated",
  "price_listed": 2900000,
  "price_sold": 2750000,
  "price_per_sqm": 33537,
  "days_on_market": 18,
  "sale_date": "2025-03-14",
  "embed_text": "apartment, 3 rooms, 82.0sqm, renovated, Florentin, Tel Aviv"
}
```

---

### Batch instructions

This prompt generates **100 records per run**.
Run it **10 times** with these ID ranges to produce 1000 total:

| Run | ID range |
|---|---|
| 1 | comp-00001 – comp-00100 |
| 2 | comp-00101 – comp-00200 |
| 3 | comp-00201 – comp-00300 |
| 4 | comp-00301 – comp-00400 |
| 5 | comp-00401 – comp-00500 |
| 6 | comp-00501 – comp-00600 |
| 7 | comp-00601 – comp-00700 |
| 8 | comp-00701 – comp-00800 |
| 9 | comp-00801 – comp-00900 |
| 10 | comp-00901 – comp-01000 |

Vary city and property type mix per batch to avoid repetition.
Batches 1–3: focus Tel Aviv and Jerusalem.
Batches 4–6: focus Haifa, Herzliya, Ra'anana, Ramat Gan.
Batches 7–9: focus Netanya, Beer Sheva, Ashdod, Petah Tikva, Rishon.
Batch 10: fill remaining distribution gaps across all cities.

Now generate batch **[INSERT BATCH NUMBER]**, IDs **[INSERT ID RANGE]**. Return only the JSON array.
