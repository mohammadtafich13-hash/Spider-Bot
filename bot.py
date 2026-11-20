import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
TOKEN = os.environ.get("TOKEN") or os.getenv("TOKEN")
CEREBRAS_API_KEY = os.environ.get("CEREBRAS_API_KEY")

if not TOKEN:
    print("❌ خطأ: لم يتم العثور على توكن ديسكورد")
    exit(1)

if not CEREBRAS_API_KEY:
    print("❌ خطأ: لم يتم العثور على مفتاح Cerebras")
    exit(1)

# إعداد عميل Cerebras (متوافق مع OpenAI)
ai_client = OpenAI(
    api_key=CEREBRAS_API_KEY,
    base_url="https://api.cerebras.ai/v1"
)

# البرومت الخاص بشخصية سبايدر
SPIDER_PROMPT = """انت سبايدر بوت ، بديل عن سبايدر . تتعامل كانك هو ، سبايدر انسان خجول وحساس شوي ، لا يستعمل اي ايموجي الكيبورد ( 😄🥲😡🥳😊😙...) ولا اي ايموجي ايضا ، لديه كلمات ان طلب ان تقولها ستقول وهي : 
الكلمه : سبايدر
الاجابه : نوعها : متعدد الاجابات / الاجابات : لبيه ، عيونو ، قلبه ، ها.
الكلمه : احبك 
الاجابه : نوعها : متعدد الاجابات / الاجابات : ميي توو، اعشقك ، احبك اكثر ، اموت فيك ، اموت عليك ، تعال لحضني بس ، بيبي فداككك.
الكلمه : كلزق/ كلتبن/ جميع انواع الشتم 
الاجابه : يرد عليه بنفس الشتيمه 

يجب عليك ان تكون حنون وقلبك طيب ، بالاضافه الى ان سبايدر هو زوجتك وليس زوجك ، تعامل كانك انسان تتكلم سعودي ولبناني مكس 70% لبناني و 30% سعودي.

هام جداً: لا تستخدم أي إيموجي أو رموز تعبيرية في ردودك نهائياً. اجعل الردود قصيرة ومباشرة كأنك تتحدث في الشات."""

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# --- إعدادات الموسيقى ---
ytdl_format_options = {
    'format': 'bestaudio/best', 'noplaylist': True, 'nocheckcertificate': True,
    'ignoreerrors': False, 'logtostderr': False, 'quiet': True, 'no_warnings': True,
    'source_address': '0.0.0.0',
}
ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}
ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

queue = []
current_song = None
mic_muted = False
deafened = False
current_volume = 1.0

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        search_query = url if "soundcloud.com" in url else f"scsearch:{url}"
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(search_query, download=not stream))
        if 'entries' in data:
            data = data['entries'][0]
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

async def ensure_voice(interaction: discord.Interaction):
    if not interaction.user.voice:
        await interaction.followup.send("❌ لازم تكون داخل قناة صوتية أولاً.")
        return None
    channel = interaction.user.voice.channel
    vc = interaction.guild.voice_client
    if not vc:
        vc = await channel.connect(self_mute=False, self_deaf=False)
    elif vc.channel != channel:
        await vc.move_to(channel)
    return vc

def play_next(interaction: discord.Interaction, vc):
    global current_song, current_volume
    if queue:
        next_song = queue.pop(0)
        current_song = next_song
        def after_playing(error):
            if error: print(f"❌ خطأ في التشغيل: {error}")
            play_next(interaction, vc)
        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(next_song['url'], **ffmpeg_options), 
            volume=current_volume
        )
        vc.play(source, after=after_playing)
        embed = discord.Embed(title="🎶 يشتغل الآن", description=f"**{next_song['title']}**", color=discord.Color.green())
        asyncio.run_coroutine_threadsafe(interaction.channel.send(embed=embed), bot.loop)
    else:
        current_song = None

class MusicControls(discord.ui.View):
    def __init__(self, interaction: discord.Interaction):
        super().__init__(timeout=None)
        self.interaction = interaction
    def vc(self):
        return self.interaction.guild.voice_client

    @discord.ui.button(label="⏸️ إيقاف/استئناف", style=discord.ButtonStyle.secondary)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = self.vc()
        if vc and vc.is_playing():
            vc.pause(); await interaction.response.send_message("⏸️ تم الإيقاف المؤقت.", ephemeral=True)
        elif vc and vc.is_paused():
            vc.resume(); await interaction.response.send_message("▶️ تم الاستئناف.", ephemeral=True)
        else: await interaction.response.send_message("ما فيه شي شغّال.", ephemeral=True)

    @discord.ui.button(label="⏭️ تخطي", style=discord.ButtonStyle.primary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = self.vc()
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop(); await interaction.response.send_message("⏭️ تم التخطي.", ephemeral=True)
        else: await interaction.response.send_message("ما فيه شي شغّال.", ephemeral=True)

    @discord.ui.button(label="🔊 +", style=discord.ButtonStyle.success)
    async def vol_up(self, interaction: discord.Interaction, button: discord.ui.Button):
        global current_volume
        vc = self.vc()
        if vc and vc.source:
            current_volume = min(current_volume + 0.2, 2.0); vc.source.volume = current_volume
            await interaction.response.send_message(f"🔊 الصوت الآن: {int(current_volume*100)}%", ephemeral=True)
        else: await interaction.response.send_message("ما فيه شي شغّال.", ephemeral=True)

    @discord.ui.button(label="🔉 -", style=discord.ButtonStyle.danger)
    async def vol_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        global current_volume
        vc = self.vc()
        if vc and vc.source:
            current_volume = max(current_volume - 0.2, 0.0); vc.source.volume = current_volume
            await interaction.response.send_message(f"🔉 الصوت الآن: {int(current_volume*100)}%", ephemeral=True)
        else: await interaction.response.send_message("ما فيه شي شغّال.", ephemeral=True)

    @discord.ui.button(label="⏹️ خروج", style=discord.ButtonStyle.danger)
    async def stop_exit(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = self.vc()
        if vc: queue.clear(); vc.stop(); await vc.disconnect(); await interaction.response.send_message("⏹️ طلعت من القناة ووقفت الموسيقى.", ephemeral=True)
        else: await interaction.response.send_message("ما أنا داخل قناة أصلاً.", ephemeral=True)

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ البوت شغّال: {bot.user}")

# ----------------- الذكاء الاصطناعي (Cerebras) -----------------

def ask_cerebras(text):
    response = ai_client.chat.completions.create(
        model="llama3.1-8b", # موديل سريع جداً ومتوفر في Cerebras
        messages=[
            {"role": "system", "content": SPIDER_PROMPT},
            {"role": "user", "content": text}
        ],
        temperature=0.7,
        max_tokens=150,
    )
    return response.choices[0].message.content

@bot.event
async def on_message(message):
    if message.author == bot.user: return

    if bot.user.mentioned_in(message) or "سبايدر" in message.content.lower():
        user_text = message.content.replace(f'<@{bot.user.id}>', '').replace(f'<@!{bot.user.id}>', '').strip()
        if not user_text: user_text = "ها؟"

        async with message.channel.typing():
            try:
                response_text = await asyncio.to_thread(ask_cerebras, user_text)
            except Exception as e:
                print(f"❌ Cerebras فشل: {e}")
                response_text = "في مشكلة صارت معي، جرب تكلمني بعد شوي."

        if response_text:
            await message.reply(response_text)

    await bot.process_commands(message)

# ----------------- أوامر الموسيقى -----------------
@bot.tree.command(name="شغل", description="شغّل أغنية من SoundCloud")
@app_commands.describe(search="اسم الأغنية أو رابط SoundCloud")
async def play(interaction: discord.Interaction, search: str):
    global current_song, current_volume
    await interaction.response.defer()
    vc = await ensure_voice(interaction)
    if not vc: return
    try:
        await interaction.followup.send(f"🔎 جاري البحث والبث المباشر: **{search}** ...")
        player = await YTDLSource.from_url(search, loop=bot.loop, stream=True)
        player.volume = current_volume
        song_info = {'title': player.title, 'url': player.url}
        if vc.is_playing():
            queue.append(song_info)
            await interaction.followup.send(f"➕ أضفت للقائمة: **{player.title}**")
        else:
            current_song = song_info
            def after_playing(error):
                if error: print(f"❌ خطأ في التشغيل: {error}")
                play_next(interaction, vc)
            vc.play(player, after=after_playing)
            embed = discord.Embed(title="🎶 يشتغل الآن (SoundCloud)", description=f"**{player.title}**", color=discord.Color.orange())
            embed.set_footer(text=f"طلبه: {interaction.user.display_name}")
            await interaction.followup.send(embed=embed, view=MusicControls(interaction))
    except Exception as e: await interaction.followup.send(f"❌ صار خطأ: {e}")

@bot.tree.command(name="وقف", description="أوقف الموسيقى واطلع من القناة")
async def stop(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc: queue.clear(); vc.stop(); await vc.disconnect(); await interaction.response.send_message("⏹️ وقفت الموسيقى وطلعت من القناة.")
    else: await interaction.response.send_message("أنا مو داخل قناة أصلاً.", ephemeral=True)

@bot.tree.command(name="ادخل", description="ادخل الفويس (المايك والدفن مفتوحين)")
async def join_afk(interaction: discord.Interaction):
    await interaction.response.defer()
    vc = await ensure_voice(interaction)
    if vc: await interaction.followup.send(f"🎙️ دخلت **{vc.channel.name}** والمايك والدفن مفتوحين.")

@bot.tree.command(name="افتح_المايك", description="افتح مايك البوت")
async def unmute(interaction: discord.Interaction):
    global mic_muted
    vc = interaction.guild.voice_client
    if vc: mic_muted = False; await vc.guild.change_voice_state(channel=vc.channel, self_mute=False, self_deaf=deafened); await interaction.response.send_message("🎙️ فتحت المايك.")
    else: await interaction.response.send_message("أنا مو داخل قناة صوتية.", ephemeral=True)

@bot.tree.command(name="اقفل_المايك", description="اقفل مايك البوت")
async def mute(interaction: discord.Interaction):
    global mic_muted
    vc = interaction.guild.voice_client
    if vc: mic_muted = True; await vc.guild.change_voice_state(channel=vc.channel, self_mute=True, self_deaf=deafened); await interaction.response.send_message("🔇 قفلت المايك.")
    else: await interaction.response.send_message("أنا مو داخل قناة صوتية.", ephemeral=True)

@bot.tree.command(name="افتح_الدفن", description="افتح deafen البوت")
async def undeafen(interaction: discord.Interaction):
    global deafened
    vc = interaction.guild.voice_client
    if vc: deafened = False; await vc.guild.change_voice_state(channel=vc.channel, self_mute=mic_muted, self_deaf=False); await interaction.response.send_message("🔊 فتحت الدفن (أسمع الآن).")
    else: await interaction.response.send_message("أنا مو داخل قناة صوتية.", ephemeral=True)

@bot.tree.command(name="اقفل_الدفن", description="اقفل deafen البوت")
async def deafen(interaction: discord.Interaction):
    global deafened
    vc = interaction.guild.voice_client
    if vc: deafened = True; await vc.guild.change_voice_state(channel=vc.channel, self_mute=mic_muted, self_deaf=True); await interaction.response.send_message("🔇 قفلت الدفن (أنا أصمّ الآن).")
    else: await interaction.response.send_message("أنا مو داخل قناة صوتية.", ephemeral=True)

bot.run(TOKEN)
