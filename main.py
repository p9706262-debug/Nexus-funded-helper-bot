
import os
import re
import json
import discord

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
ADMIN_CHANNEL_ID = int(os.environ["ADMIN_CHANNEL_ID"])
DATA_FILE = "faqs.json"

# Common words ignored when matching
STOP_WORDS = {
    "the", "a", "an", "is", "are", "do", "does", "how", "what", "i", "my",
    "to", "of", "in", "on", "for", "can", "you", "it", "be", "and", "or",
    "at", "with", "this", "that", "me", "we", "our", "there", "when", "where",
}

# Words that mean the same thing get mapped to one form
SYNONYMS = {
    "launching": "launch", "launches": "launch", "launched": "launch",
    "release": "launch", "releasing": "launch", "opening": "launch",
    "open": "launch", "live": "launch", "going": "launch",
    "firm": "company", "business": "company", "startup": "company",
    "date": "when", "time": "when",
}

# Words that usually start a question
QUESTION_STARTERS = {
    "what", "when", "where", "who", "why", "how", "is", "are", "can",
    "does", "do", "will", "should", "which",
}

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


def load_faqs():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_faqs(faqs):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(faqs, f, indent=2, ensure_ascii=False)


def normalize(word):
    word = SYNONYMS.get(word, word)
    for suffix in ("ing", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def keywords(text):
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {normalize(w) for w in words} - {normalize(w) for w in STOP_WORDS}


def find_answer(question):
    asked = keywords(question)
    best, best_score = None, 0
    for faq in load_faqs():
        faq_words = keywords(faq["question"])
        score = len(asked & faq_words)
        # Need 2 shared words, or all words of a short saved question
        enough = score >= 2 or (score >= 1 and score == len(faq_words))
        if enough and score > best_score:
            best, best_score = faq, score
    return best


def looks_like_question(text):
    text = text.strip()
    if len(text) < 8:
        return False
    if "?" in text:
        return True
    first_word = re.findall(r"[a-z]+", text.lower())[:1]
    return bool(first_word) and first_word[0] in QUESTION_STARTERS


class AnswerModal(discord.ui.Modal, title="Add an answer"):
    def __init__(self, question, answer_view, alert):
        super().__init__()
        self.answer_view = answer_view
        self.alert = alert
        self.question_box = discord.ui.TextInput(
            label="Question", style=discord.TextStyle.paragraph,
            default=question, max_length=300,
        )
        self.answer_box = discord.ui.TextInput(
            label="Answer", style=discord.TextStyle.paragraph,
            max_length=1000,
        )
        self.add_item(self.question_box)
        self.add_item(self.answer_box)

    async def on_submit(self, interaction: discord.Interaction):
        question = self.question_box.value.strip()
        answer = self.answer_box.value.strip()

        faqs = load_faqs()
        faqs.append({"question": question, "answer": answer})
        save_faqs(faqs)

        await interaction.response.send_message(
            "✅ Saved. Future questions like this will be answered automatically.",
            ephemeral=True,
        )

        # Reply to the member who asked
        try:
            await self.answer_view.asker_message.reply(f"**{answer}**")
        except discord.HTTPException:
            pass

        # Disable the button on the alert
        for item in self.answer_view.children:
            item.disabled = True
        await self.alert.edit(
            content=f"✅ Answered by {interaction.user.mention}",
            view=self.answer_view,
        )


class AnswerView(discord.ui.View):
    def __init__(self, question, asker_message):
        super().__init__(timeout=None)
        self.question = question
        self.asker_message = asker_message

    @discord.ui.button(label="Add answer", style=discord.ButtonStyle.green, emoji="✏️")
    async def add_answer(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "Only admins can answer this.", ephemeral=True
            )
            return
        await interaction.response.send_modal(
            AnswerModal(self.question, self, interaction.message)
        )


@client.event
async def on_ready():
    print(f"Logged in as {client.user}")


@client.event
async def on_message(message: discord.Message):
    # Ignore bots, DMs, and the admin channel itself
    if message.author.bot or not message.guild:
        return
    if message.channel.id == ADMIN_CHANNEL_ID:
        return

    # Answer automatically if we already know the answer
    faq = find_answer(message.content)
    if faq:
        await message.reply(f"**{faq['answer']}**")
        return

    # Otherwise, alert the admins if it's a question
    if looks_like_question(message.content):
        admin_channel = client.get_channel(ADMIN_CHANNEL_ID)
        if admin_channel:
            embed = discord.Embed(
                title="❓ Unanswered question",
                description=message.content[:1000],
                color=discord.Color.orange(),
            )
            embed.add_field(name="Asked by", value=message.author.mention)
            embed.add_field(name="Channel", value=message.channel.mention)
            embed.add_field(name="Jump to message", value=message.jump_url, inline=False)
            await admin_channel.send(
                embed=embed,
                view=AnswerView(message.content[:300], message),
            )

        await message.reply(
            "Good question! I don't have that answer yet, so I've asked the team. "
            "You'll get a reply here soon."
        )


client.run(DISCORD_TOKEN)
