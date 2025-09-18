from html.parser import HTMLParser
import re
import json
import base64
import os
import random
import time
from urllib.parse import urljoin

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import (
    ExtractorError,
    int_or_none,
    js_to_json,
    url_or_none,
    sanitized_Request,
    unified_strdate,
    unified_timestamp,
    update_url_query,
    urlencode_postdata,
)

class VoeIE(InfoExtractor):
    IE_NAME = 'voe'
    IE_DESC = 'VOE.SX'
    _VALID_URL = r'https?://voe\.sx/(e/)?(?P<id>[a-z0-9]+)'
    _TEST = {
        'url': 'https://voe.sx/e/ng7ja5n5n2y8',
        'info_dict': {
            'id': 'ng7ja5n5n2y8',
            'title': 'md5:a86687fb962742f04652aee19ad34e06',
            'thumbnail': r're:^https?://.*\.jpg$',
            'ext': 'm3u8',
        },
    }

    @staticmethod
    def _rot13(text):
        """Apply ROT13 cipher (letters only)."""
        out = []
        for ch in text:
            o = ord(ch)
            if 65 <= o <= 90:
                out.append(chr(((o - 65 + 13) % 26) + 65))
            elif 97 <= o <= 122:
                out.append(chr(((o - 97 + 13) % 26) + 97))
            else:
                out.append(ch)
        return ''.join(out)

    @staticmethod
    def _replace_patterns(txt):
        """Strip marker substrings used as obfuscation separators."""
        for pat in ['@$', '^^', '~@', '%?', '*~', '!!', '#&']:
            txt = txt.replace(pat, '')
        return txt

    @staticmethod
    def _shift_chars(text, shift):
        """Shift character code-points by *-shift* (decode)."""
        return ''.join(chr(ord(c) - shift) for c in text)

    @staticmethod
    def _safe_b64_decode(s):
        """Base64 decode with safe padding and utf-8 fallback."""
        pad = len(s) % 4
        if pad:
            s += '=' * (4 - pad)
        try:
            return base64.b64decode(s).decode('utf-8', errors='replace')
        except Exception as e:
            return ''

    @classmethod
    def deobfuscate_embedded_json(cls, raw_json):
        """Deobfuscate the embedded JSON data."""
        try:
            # Try to parse as JSON first
            data = json.loads(raw_json)
            if isinstance(data, list) and data and isinstance(data[0], str):
                # If it's a list with a string, use that
                obf = data[0]
            else:
                return data
        except json.JSONDecodeError:
            return None

        try:
            if not raw_json or not isinstance(raw_json, str):
                return None
                
            # Try to parse as JSON first
            try:
                data = json.loads(raw_json)
                if isinstance(data, list) and data and isinstance(data[0], str):
                    # If it's a list with a string, use that
                    obf = data[0]
                else:
                    return data
            except json.JSONDecodeError:
                obf = raw_json
            
            # ROT13 decode
            step1 = cls._rot13(obf)
            
            # Replace patterns
            step2 = cls._replace_patterns(step1)
            
            # Base64 decode
            step3 = cls._safe_b64_decode(step2)
            if not step3:
                return None
            
            # Shift characters back by 3
            step4 = cls._shift_chars(step3, 3)
            
            # Reverse string
            step5 = step4[::-1]
            
            # Final Base64 decode
            step6 = cls._safe_b64_decode(step5)
            if not step6:
                return None
            
            # Try to parse as JSON
            try:
                return json.loads(step6)
            except json.JSONDecodeError:
                return step6
                
        except Exception as e:
            return None

    def _extract_redirect_url(self, webpage):
        """Extract redirect URL from JavaScript redirect."""
        # Look for window.location.href patterns
        patterns = [
            r'window\.location\.href\s*=\s*["\']([^"\']+)["\']',
            r'window\.location\s*=\s*["\']([^"\']+)["\']',
            r'window\.location\.replace\(\s*["\']([^"\']+)["\']',
            r'window\.location\.assign\(\s*["\']([^"\']+)["\']',
            r'<meta\s+http-equiv="refresh"\s+content="\d+;\s*url=([^"]+)"\s*/*>',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, webpage, re.IGNORECASE)
            if match:
                redirect_url = match.group(1)
                # Handle relative URLs
                if redirect_url.startswith('//'):
                    redirect_url = 'https:' + redirect_url
                elif redirect_url.startswith('/'):
                    redirect_url = 'https://voe.sx' + redirect_url
                elif not (redirect_url.startswith('http://') or redirect_url.startswith('https://')):
                    redirect_url = 'https://voe.sx/' + redirect_url.lstrip('/')
                return redirect_url
        return None

        """Recursively extract video URLs from JSON data."""
        try:
            if not data:
                return
                
            if isinstance(data, dict):
                # Check for direct access URLs first
                if 'direct_access_url' in data:
                    url = data['direct_access_url']
                    self.to_screen(f'Found direct access URL: {url}')
                    url_list.append(url)
                    return
                    
                # Check for source URLs
                if 'source' in data:
                    url = data['source']
                    self.to_screen(f'Found source URL: {url}')
                    url_list.append(url)
                    return
                    
                # Check for mp4/hls keys
                for key in ('mp4', 'hls', 'url', 'src', 'file'):
                    if key in data and isinstance(data[key], str) and any(ext in data[key] for ext in ('.mp4', '.m3u8', '.mpd')):
                        url = data[key]
                        self.to_screen(f'Found {key} URL: {url}')
                        url_list.append(url)
                        return
                
                # Recursively check all values in the dictionary
                for value in data.values():
                    self._extract_urls_from_json(value, url_list)
                    
            elif isinstance(data, list):
                # Recursively check all items in the list
                for item in data:
                    self._extract_urls_from_json(item, url_list)
                    
            elif isinstance(data, str):
                # Try to extract URLs from string
                for pattern in [
                    r'(https?://[^\s"]+\.(?:mp4|m3u8|mpd)[^\s"]*)',
                    r'(//[^\s"]+\.(?:mp4|m3u8|mpd)[^\s"]*)'
                ]:
                    for match in re.finditer(pattern, data):
                        url = match.group(1)
                        if url.startswith('//'):
                            url = 'https:' + url
                        self.to_screen(f'Found URL in string: {url}')
                        url_list.append(url)
                        
        except Exception as e:
            self.report_warning(f'Error extracting URLs from JSON: {str(e)}')

    def _html_extract_title(self, webpage):
        return (self._og_search_title(webpage, default=None) or 
                self._html_search_meta('title', webpage, default='').strip() or 
                self._html_search_regex(r'<title>([^<]+)</title>', webpage, 'title', default='').strip())
    
    def _real_extract(self, url):
        video_id = self._match_id(url)
        self.to_screen(f'Starting extraction for video ID: {video_id}')
        
        # Create debug directory if it doesn't exist
        debug_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'debug')
        os.makedirs(debug_dir, exist_ok=True)
        
        def save_debug_file(prefix, content):
            """Helper to save debug files with timestamp and random suffix"""
            if not content:
                return
                
            timestamp = int(time.time())
            rand_suffix = ''.join(random.choices('abcdef0123456789', k=6))
            filename = f'{prefix}_{video_id}_{timestamp}_{rand_suffix}.html'
            filepath = os.path.join(debug_dir, filename)
            
            try:
                if isinstance(content, (dict, list)):
                    content = json.dumps(content, indent=2, ensure_ascii=False)
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(str(content))
                self.to_screen(f'Saved debug file: {filepath}')
                return filepath
            except Exception as e:
                self.report_warning(f'Error saving debug file {filename}: {str(e)}')
                return None
        
        # Try to bypass any potential bot detection
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Referer': 'https://voe.sx/',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
            'TE': 'trailers',
        }
        
        # First, fetch the initial page which might contain a redirect
        try:
            # Add some random delay to avoid rate limiting
            time.sleep(random.uniform(1.0, 3.0))
            
            # Fetch the initial page
            webpage = self._download_webpage(
                'https://voe.sx/e/%s' % video_id, 
                video_id,
                note='Fetching initial page',
                errnote='Failed to fetch initial page',
                headers=headers,
                expected_status=None)
            
            # Save the initial page for debugging
            save_debug_file('initial', webpage)
            
            # Check for JavaScript redirect
            max_redirects = 3
            for i in range(max_redirects):
                redirect_url = self._extract_redirect_url(webpage)
                if not redirect_url:
                    self.to_screen('No more redirects found')
                    break
                    
                self.to_screen(f'Following redirect to: {redirect_url}')
                try:
                    # Add some random delay between redirects
                    time.sleep(random.uniform(0.5, 2.0))
                    
                    # Update referer to the current URL
                    headers['Referer'] = redirect_url
                    
                    webpage = self._download_webpage(
                        redirect_url, 
                        video_id,
                        note=f'Fetching redirected page ({i+1}/{max_redirects})',
                        errnote=f'Failed to fetch redirected page ({i+1}/{max_redirects})',
                        headers=headers,
                        expected_status=None)
                    
                    # Save the redirected page for debugging
                    save_debug_file(f'redirect_{i+1}', webpage)
                    
                    if not webpage or len(webpage) < 100:
                        self.report_warning(f'Empty or too short response from redirect {i+1}')
                        break
                        
                except Exception as e:
                    self.report_warning(f'Error following redirect: {str(e)}')
                    break
                    
        except Exception as e:
            self.report_warning(f'Error during initial fetch: {str(e)}')
            if 'webpage' not in locals() or not webpage:
                raise ExtractorError(f'Failed to fetch webpage: {str(e)}')
        
        # Extract title
        title = self._html_extract_title(webpage)
        if not title or len(title) < 3:  # Very short title might be invalid
            title = f'Video {video_id}'
            self.report_warning('Could not extract title, using fallback')

        # Save the final webpage for debugging
        save_debug_file('final', webpage)
        
        # Try to find video URL using different methods
        video_urls = []
        
        # Method 1: Look for direct video URLs in the page
        video_patterns = [
            r'"sources"\s*:\s*\[\s*{\s*"src"\s*:\s*"([^"]+\.(?:mp4|m3u8|mpd))"',
            r'"file"\s*:\s*"([^"]+\.(?:mp4|m3u8|mpd))"',
            r'"url"\s*:\s*"([^"]+\.(?:mp4|m3u8|mpd))"',
            r'source\s+src=["\']([^"\']+\.(?:mp4|m3u8|mpd))["\']',
            r'<video[^>]+src=["\']([^"\']+\.(?:mp4|m3u8|mpd))["\']',
            r'(https?://[^"\'\s]+\.(?:mp4|m3u8|mpd)[^"\'\s]*)',  # Direct URL match
        ]
        
        for pattern in video_patterns:
            try:
                matches = re.findall(pattern, webpage)
                if matches:
                    video_urls.extend(matches)
                    self.to_screen(f'Found {len(matches)} URLs with pattern: {pattern[:50]}...')
            except Exception as e:
                self.report_warning(f'Error with pattern {pattern}: {str(e)}')
        
        # Method 2: Parse JSON data from script tags
        script_patterns = [
            r'<script[^>]*>\s*({[^<]+})\s*</script>',
            r'<script[^>]+type=["\']application/json["\'][^>]*>([^<]+)</script>',
            r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>([^<]+)</script>',  # Next.js data
            r'window\.__NUXT__\s*=\s*({[^<]+});?',  # Nuxt.js data
        ]
        
        for pattern in script_patterns:
            try:
                for match in re.finditer(pattern, webpage, re.DOTALL):
                    try:
                        script_content = match.group(1)
                        if not script_content:
                            continue
                            
                        # Clean up the script content
                        script_content = re.sub(r'<!--.*?-->', '', script_content, flags=re.DOTALL)
                        script_content = script_content.strip()
                        
                        if not script_content:
                            continue
                            
                        self.to_screen(f'Found script content: {script_content[:200]}...')
                        
                        json_result = self.deobfuscate_embedded_json(script_content)                            
                    except Exception as e:
                        self.report_warning(f'Error with script content: {str(e)}')
            except Exception as e:
                self.report_warning(f'Error with script pattern {pattern}: {str(e)}')
        
        # Process found URLs
        formats = []

        f_url = url_or_none(json_result['source'])
        if f_url:
            formats.extend(self._extract_m3u8_formats(
                f_url, video_id, entry_protocol='m3u8_native', fatal=False))
        f_url = url_or_none(json_result['direct_access_url'])
        if f_url:
            formats.append({
                'url': f_url,
                'ext': 'mp4',
                'height': int_or_none(json_result.get('video_height')),
            })

        thumbnail = url_or_none(self._search_regex(
            r'(?:VOEPlayer.|data-)poster\s*=\s*(["\'])(?P<thumbnail>(?:(?!\1)\S)+)\1',
            webpage, 'thumbnail', group='thumbnail', default=None))

        return {
            'id': video_id,
            'title': title,
            'formats': formats,
            'thumbnail': thumbnail,
        }