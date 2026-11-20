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

if not TOKEN or not CEREBRAS_API_KEY:
    print("❌ تأكد من وجود TOKEN و CEREBRAS_API_KEY")
    exit(1)

# إعداد Cerebras
ai_client = OpenAI(api_key=CEREBRAS_API_KEY, base_url="https://api.cerebras.ai/v1")

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
intents.message_content = True
intents.dm_messages = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- إعدادات الموسيقى ---
ytdl_format_options = {'format': 'bestaudio/best', 'noplaylist': True, 'quiet': True}
ffmpeg_options = {'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', 'options': '-vn'}
ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

queue, current_song, mic_muted, deafened, current_volume = [], None, False, False, 1.0

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
        if 'entries' in data: data = data['entries'][0]
        return cls(discord.FFmpegPCMAudio(data['url'], **ffmpeg_options), data=data)

async def ensure_voice(interaction: discord.Interaction):
    if not interaction.guild: return None
    if not interaction.user.voice:
        await interaction.followup.send("❌ لازم تكون داخل قناة صوتية.")
        return None
    channel = interaction.user.voice.channel
    vc = interaction.guild.voice_client
    if not vc: vc = await channel.connect(self_mute=False, self_deaf=False)
    elif vc.channel != channel: await vc.move_to(channel)
    return vc

def play_next(interaction: discord.Interaction, vc):
    global current_song, current_volume
    if queue:
        next_song = queue.pop(0)
        current_song = next_song
        def after_playing(error):
            if error: print(f"❌ خطأ: {error}")
            play_next(interaction, vc)
        source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(next_song['url'], **ffmpeg_options), volume=current_volume)
        vc.play(source, after=after_playing)
        embed = discord.Embed(title="🎶 يشتغل الآن", description=f"**{next_song['title']}**", color=discord.Color.green())
        asyncio.run_coroutine_threadsafe(interaction.channel.send(embed=embed), bot.loop)
    else: current_song = None

# --- الذكاء الاصطناعي ---
def ask_ai(text):
    response = ai_client.chat.completions.create(
        model="llama3.1-8b",
        messages=[{"role": "system", "content": SPIDER_PROMPT}, {"role": "user", "content": text}],
        temperature=0.7, max_tokens=200,
    )
    return response.choices[0].message.content

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ المساعد الشخصي شغّال: {bot.user}")

# --- الرد التلقائي في الخاص (DM) ---
@bot.event
async def on_message(message):
    if message.author == bot.user: return
    if isinstance(message.channel, discord.DMChannel):
        async with message.channel.typing():
            try:
                response_text = await asyncio.to_thread(ask_ai, message.content)
                await message.reply(response_text)
            except Exception as e:
                await message.reply("في مشكلة صارت، جرب بعدين.")
    await bot.process_commands(message)

# --- الأوامر (Slash Commands) ---

@bot.tree.command(name="اسأل", description="كلم سبايدر في أي مكان")
async def ask(interaction: discord.Interaction, question: str):
    await interaction.response.defer()
    try:
        response_text = await asyncio.to_thread(ask_ai, question)
        await interaction.followup.send(response_text)
    except:
        await interaction.followup.send("في مشكلة صارت.")

@bot.tree.command(name="تكلم_عني", description="البوت يرسل رسالة نيابة عنك في الشات")
@app_commands.describe(text="الرسالة اللي تبيها تنرسل")
async def speak_for_me(interaction: discord.Interaction, text: str):
    if isinstance(interaction.channel, discord.DMChannel):
        await interaction.response.send_message("هذا الأمر يشتغل فقط في السيرفرات.", ephemeral=True)
        return
    await interaction.response.send_message(f"✅ تم إرسال رسالتك نيابة عنك.", ephemeral=True)
    await interaction.channel.send(f"**{interaction.user.display_name}:** {text}")

@bot.tree.command(name="ترجم", description="ترجم النص اللي تكتبه للعربية أو الإنجليزية")
async def translate(interaction: discord.Interaction, text: str):
    await interaction.response.defer()
    prompt = f"ترجم النص التالي ترجمة دقيقة جداً. إذا كان إنجليزي ترجمه عربي، وإذا عربي ترجمه إنجليزي. لا تكتب أي شيء غير الترجمة:\n{text}"
    try:
        # نستخدم برومت الترجمة بدل برومت سبايدر
        response = ai_client.chat.completions.create(
            model="llama3.1-8b",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        await interaction.followup.send(f"🌐 **الترجمة:**\n{response.choices[0].message.content}")
    except:
        await interaction.followup.send("ما قدرت أترجم، جرب بعدين.")

@bot.tree.command(name="احصائيات", description="يعطيك معلومات عن السيرفر")
async def stats(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("هذا الأمر للسيرفرات فقط.", ephemeral=True)
        return
    guild = interaction.guild
    embed = discord.Embed(title=f"📊 إحصائيات {guild.name}", color=discord.Color.blue())
    embed.add_field(name="الأعضاء", value=str(guild.member_count))
    embed.add_field(name="القنوات", value=str(len(guild.channels)))
    embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
    await interaction.response.send_message(embed=embed)

# --- أوامر الموسيقى ---
@bot.tree.command(name="شغل", description="شغّل أغنية من SoundCloud")
async def play(interaction: discord.Interaction, search: str):
    await interaction.response.defer()
    vc = await ensure_voice(interaction)
    if not vc: return
    try:
        player = await YTDLSource.from_url(search, loop=bot.loop, stream=True)
        player.volume = current_volume
        song_info = {'title': player.title, 'url': player.url}
        if vc.is_playing():
            queue.append(song_info)
            await interaction.followup.send(f"➕ أضفت للقائمة: **{player.title}**")
        else:
            global current_song
            current_song = song_info
            vc.play(player, after=lambda e: play_next(interaction, vc))
            await interaction.followup.send(f"🎶 يشتغل الآن: **{player.title}**")
    except Exception as e: await interaction.followup.send(f"❌ صار خطأ: {e}")

@bot.tree.command(name="وقف", description="أوقف الموسيقى واطلع من القناة")
async def stop(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc: queue.clear(); vc.stop(); await vc.disconnect(); await interaction.response.send_message("⏹️ طلعت من القناة.")
    else: await interaction.response.send_message("أنا مو داخل قناة.", ephemeral=True)

@bot.tree.command(name="ادخل", description="ادخل الفويس بصمت")
async def join_afk(interaction: discord.Interaction):
    await interaction.response.defer()
    vc = await ensure_voice(interaction)
    if vc: await interaction.followup.send(f"🎙️ دخلت **{vc.channel.name}**.")

@bot.tree.command(name="افتح_المايك")
async def unmute(interaction: discord.Interaction):
    global mic_muted
    vc = interaction.guild.voice_client
    if vc: mic_muted = False; await vc.guild.change_voice_state(channel=vc.channel, self_mute=False, self_deaf=deafened); await interaction.response.send_message("🎙️ فتحت المايك.")
    else: await interaction.response.send_message("أنا مو داخل قناة.", ephemeral=True)

@bot.tree.command(name="اقفل_المايك")
async def mute(interaction: discord.Interaction):
    global mic_muted
    vc = interaction.guild.voice_client
    if vc: mic_muted = True; await vc.guild.change_voice_state(channel=vc.channel, self_mute=True, self_deaf=deafened); await interaction.response.send_message("🔇 قفلت المايك.")
    else: await interaction.response.send_message("أنا مو داخل قناة.", ephemeral=True)

@bot.tree.command(name="افتح_الدفن")
async def undeafen(interaction: discord.Interaction):
    global deafened
    vc = interaction.guild.voice_client
    if vc: deafened = False; await vc.guild.change_voice_state(channel=vc.channel, self_mute=mic_muted, self_deaf=False); await interaction.response.send_message("🔊 فتحت الدفن.")
    else: await interaction.response.send_message("أنا مو داخل قناة.", ephemeral=True)

@bot.tree.command(name="اقفل_الدفن")
async def deafen(interaction: discord.Interaction):
    global deafened
    vc = interaction.guild.voice_client
    if vc: deafened = True; await vc.guild.change_voice_state(channel=vc.channel, self_mute=mic_muted, self_deaf=True); await interaction.response.send_message("🔇 قفلت الدفن.")
    else: await interaction.response.send_message("أنا مو داخل قناة.", ephemeral=True)

bot.run(TOKEN)
