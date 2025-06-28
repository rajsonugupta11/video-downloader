from flask import Flask, request, send_from_directory, render_template, jsonify
import yt_dlp
import os
import threading
import time

# Initialize Flask application
app = Flask(__name__)
DOWNLOAD_FOLDER = 'downloads'
progress_data = {}

# Ensure download directory exists
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/progress')
def get_progress():
    return jsonify(progress_data.get('error', progress_data))

def progress_hook(d):
    if d['status'] == 'downloading':
        progress_data['progress'] = d.get('downloaded_bytes', 0)
        progress_data['total'] = d.get('total_bytes', d.get('total_bytes_estimate', 0))
        progress_data['speed'] = d.get('speed', 0)
        progress_data['eta'] = d.get('eta', 0)
        progress_data['percent'] = round((progress_data['progress'] / progress_data['total']) * 100, 2) if progress_data['total'] else 0

@app.route('/download', methods=['POST'])
def download():
    global progress_data
    data = request.get_json()
    url = data.get('url')
    download_type = data.get('type')

    if not url or not download_type:
        return jsonify({'error': 'URL or type missing'}), 400

    url = url.replace("youtube.com/shorts/", "youtube.com/watch?v=")

    try:
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl_probe:
            info_dict = ydl_probe.extract_info(url, download=False)
            base_title = info_dict.get('title', 'downloaded_file').replace(' ', '_')
            base_title = ''.join(c for c in base_title if c.isalnum() or c in ('_', '-')).rstrip()

        ext = 'mp3' if download_type == 'audio' else 'mp4'
        filename = os.path.join(DOWNLOAD_FOLDER, f"{base_title}.{ext}")

        counter = 1
        while os.path.exists(filename):
            filename = os.path.join(DOWNLOAD_FOLDER, f"{base_title}_{counter}.{ext}")
            counter += 1

        progress_data = {
            'percent': 0,
            'eta': 0,
            'filename': None,
            'progress': 0,
            'total': 0,
            'speed': 0,
        }

        ydl_opts = {
            'outtmpl': filename.replace('\\', '/'),
            'quiet': True,
            'restrictfilenames': True,
            'merge_output_format': 'mp4',
            'noplaylist': True,
            'progress_hooks': [progress_hook],
            'overwrites': True
        }

        if download_type == 'audio':
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]
            })
        elif download_type == 'video':
            ydl_opts.update({
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'merge_output_format': 'mp4',
            })
        else:
            return jsonify({'error': 'Invalid download type'}), 400

        def download_thread():
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)

                    if 'requested_downloads' in info and isinstance(info['requested_downloads'], list):
                        final_path = info['requested_downloads'][0].get('filepath', '')
                    else:
                        final_path = ydl.prepare_filename(info)

                    if download_type == 'audio':
                        final_path = final_path.rsplit('.', 1)[0] + '.mp3'
                    else:
                        final_path = final_path.rsplit('.', 1)[0] + '.mp4'

                    progress_data['filename'] = os.path.basename(final_path)
            except Exception as e:
                progress_data['error'] = str(e)

        threading.Thread(target=download_thread).start()
        return jsonify({'started': True})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/downloads/<filename>')
def serve_file(filename):
    file_path = os.path.join(DOWNLOAD_FOLDER, filename)
    response = send_from_directory(DOWNLOAD_FOLDER, filename, as_attachment=True)

    @response.call_on_close
    def remove_file():
        try:
            os.remove(file_path)
            print(f"Deleted after download: {filename}")
        except Exception as e:
            print(f"Failed to delete {filename}: {e}")

    return response

# ✅ Background thread to clean up old files
def cleanup_old_files():
    while True:
        now = time.time()
        for fname in os.listdir(DOWNLOAD_FOLDER):
            path = os.path.join(DOWNLOAD_FOLDER, fname)
            if os.path.isfile(path):
                if now - os.path.getmtime(path) > 600:  # older than 10 minutes
                    try:
                        os.remove(path)
                        print(f"Deleted old file: {fname}")
                    except Exception as e:
                        print(f"Error deleting old file {fname}: {e}")
        time.sleep(300)  # run every 5 minutes

# Start cleanup thread
threading.Thread(target=cleanup_old_files, daemon=True).start()

if __name__ == '__main__':
    from os import environ
    port = int(environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
