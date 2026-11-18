import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("TOKEN")

if not TOKEN:
    print("❌ خطأ: لم يتم العثور على توكن ديسكورد في ملف .env")
    exit(1)

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# إعدادات ساوند كلاود (تحميل مؤقت لضمان عمل الصوت 100%)
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(id)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'source_address': '0.0.0.0',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
}

ffmpeg_options = {
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

queue = []
current_song = None
mic_muted = False
deafened = False
current_volume = 1.0

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5, filename=None):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.filename = filename

    @classmethod
    async def from_url(cls, url, *, loop=None):
        loop = loop or asyncio.get_event_loop()
        search_query = url if "soundcloud.com" in url else f"scsearch:{url}"
            
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(search_query, download=True))
        
        if 'entries' in data:
            data = data['entries'][0]
            
        filename = ytdl.prepare_filename(data)
        base, _ = os.path.splitext(filename)
        filename = base + '.mp3'
        
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data, filename=filename)

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
        
        if current_song and os.path.exists(current_song['file']):
            try: os.remove(current_song['file'])
            except: pass
                
        current_song = next_song
        
        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(next_song['file'], **ffmpeg_options), 
            volume=current_volume
        )
        
        vc.play(source, after=lambda e: play_next(interaction, vc))
        
        embed = discord.Embed(title="🎶 يشتغل الآن", description=f"**{next_song['title']}**", color=discord.Color.green())
        asyncio.run_coroutine_threadsafe(interaction.channel.send(embed=embed), bot.loop)
    else:
        if current_song and os.path.exists(current_song['file']):
            try: os.remove(current_song['file'])
            except: pass
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
            vc.pause()
            await interaction.response.send_message("⏸️ تم الإيقاف المؤقت.", ephemeral=True)
        elif vc and vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ تم الاستئناف.", ephemeral=True)
        else:
            await interaction.response.send_message("ما فيه شي شغّال.", ephemeral=True)

    @discord.ui.button(label="⏭️ تخطي", style=discord.ButtonStyle.primary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = self.vc()
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            await interaction.response.send_message("⏭️ تم التخطي.", ephemeral=True)
        else:
            await interaction.response.send_message("ما فيه شي شغّال.", ephemeral=True)

    @discord.ui.button(label="🔊 +", style=discord.ButtonStyle.success)
    async def vol_up(self, interaction: discord.Interaction, button: discord.ui.Button):
        global current_volume
        vc = self.vc()
        if vc and vc.source:
            current_volume = min(current_volume + 0.2, 2.0)
            vc.source.volume = current_volume
            await interaction.response.send_message(f"🔊 الصوت الآن: {int(current_volume*100)}%", ephemeral=True)
        else:
            await interaction.response.send_message("ما فيه شي شغّال.", ephemeral=True)

    @discord.ui.button(label="🔉 -", style=discord.ButtonStyle.danger)
    async def vol_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        global current_volume
        vc = self.vc()
        if vc and vc.source:
            current_volume = max(current_volume - 0.2, 0.0)
            vc.source.volume = current_volume
            await interaction.response.send_message(f"🔉 الصوت الآن: {int(current_volume*100)}%", ephemeral=True)
        else:
            await interaction.response.send_message("ما فيه شي شغّال.", ephemeral=True)

    @discord.ui.button(label="⏹️ خروج", style=discord.ButtonStyle.danger)
    async def stop_exit(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = self.vc()
        if vc:
            queue.clear()
            vc.stop()
            await vc.disconnect()
            await interaction.response.send_message("⏹️ طلعت من القناة ووقفت الموسيقى.", ephemeral=True)
        else:
            await interaction.response.send_message("ما أنا داخل قناة أصلاً.", ephemeral=True)

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ البوت شغّال: {bot.user}")

@bot.tree.command(name="شغل", description="شغّل أغنية من SoundCloud")
@app_commands.describe(search="اسم الأغنية أو رابط SoundCloud")
async def play(interaction: discord.Interaction, search: str):
    global current_song, current_volume
    await interaction.response.defer()
    
    vc = await ensure_voice(interaction)
    if not vc: return
        
    try:
        await interaction.followup.send(f"⏳ جاري تحميل الأغنية: **{search}** ...")
        
        player = await YTDLSource.from_url(search, loop=bot.loop)
        player.volume = current_volume
        
        song_info = {'title': player.title, 'file': player.filename}
        
        if vc.is_playing():
            queue.append(song_info)
            await interaction.followup.send(f"➕ أضفت للقائمة: **{player.title}**")
        else:
            current_song = song_info
            vc.play(player, after=lambda e: play_next(interaction, vc))
            
            embed = discord.Embed(title="🎶 يشتغل الآن", description=f"**{player.title}**", color=discord.Color.green())
            embed.set_footer(text=f"طلبه: {interaction.user.display_name}")
            await interaction.followup.send(embed=embed, view=MusicControls(interaction))
            
    except Exception as e:
        await interaction.followup.send(f"❌ صار خطأ: {e}")

@bot.tree.command(name="وقف", description="أوقف الموسيقى واطلع من القناة")
async def stop(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc:
        queue.clear()
        vc.stop()
        await vc.disconnect()
        await interaction.response.send_message("⏹️ وقفت الموسيقى وطلعت من القناة.")
    else:
        await interaction.response.send_message("أنا مو داخل قناة أصلاً.", ephemeral=True)

@bot.tree.command(name="ادخل", description="ادخل الفويس (المايك والدفن مفتوحين)")
async def join_afk(interaction: discord.Interaction):
    await interaction.response.defer()
    vc = await ensure_voice(interaction)
    if vc:
        await interaction.followup.send(f"🎙️ دخلت **{vc.channel.name}** والمايك والدفن مفتوحين.")

@bot.tree.command(name="افتح_المايك", description="افتح مايك البوت")
async def unmute(interaction: discord.Interaction):
    global mic_muted
    vc = interaction.guild.voice_client
    if vc:
        mic_muted = False
        await vc.guild.change_voice_state(channel=vc.channel, self_mute=False, self_deaf=deafened)
        await interaction.response.send_message("🎙️ فتحت المايك.")
    else:
        await interaction.response.send_message("أنا مو داخل قناة صوتية.", ephemeral=True)

@bot.tree.command(name="اقفل_المايك", description="اقفل مايك البوت")
async def mute(interaction: discord.Interaction):
    global mic_muted
    vc = interaction.guild.voice_client
    if vc:
        mic_muted = True
        await vc.guild.change_voice_state(channel=vc.channel, self_mute=True, self_deaf=deafened)
        await interaction.response.send_message("🔇 قفلت المايك.")
    else:
        await interaction.response.send_message("أنا مو داخل قناة صوتية.", ephemeral=True)

@bot.tree.command(name="افتح_الدفن", description="افتح deafen البوت")
async def undeafen(interaction: discord.Interaction):
    global deafened
    vc = interaction.guild.voice_client
    if vc:
        deafened = False
        await vc.guild.change_voice_state(channel=vc.channel, self_mute=mic_muted, self_deaf=False)
        await interaction.response.send_message("🔊 فتحت الدفن (أسمع الآن).")
    else:
        await interaction.response.send_message("أنا مو داخل قناة صوتية.", ephemeral=True)

@bot.tree.command(name="اقفل_الدفن", description="اقفل deafen البوت")
async def deafen(interaction: discord.Interaction):
    global deafened
    vc = interaction.guild.voice_client
    if vc:
        deafened = True
        await vc.guild.change_voice_state(channel=vc.channel, self_mute=mic_muted, self_deaf=True)
        await interaction.response.send_message("🔇 قفلت الدفن (أنا أصمّ الآن).")
    else:
        await interaction.response.send_message("أنا مو داخل قناة صوتية.", ephemeral=True)

bot.run(TOKEN)
