def clean_text(text):
    lines = text.split("\n")

    cleaned = []
    seen = set()

    junk_words = ["help", "sign in", "privacy policy", "terms", "cookies", "feedback"]

    for line in lines:
        line = line.strip()

        if len(line) < 40:
            continue

        if any(j in line.lower() for j in junk_words):
            continue

        if line in seen:
            continue
        seen.add(line)

        cleaned.append(line)

    return "\n".join(cleaned)