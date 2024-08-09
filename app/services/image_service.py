import os
from io import BytesIO
from flask import current_app
import redis
from PIL import Image, ImageDraw, ImageFont
import logging

class ImageService:
    TEXT_COLOR_NEW_SPIRIT = "#e741bf"
    TEXT_COLOR_LACQUER = "white"
    USER_TEXT_WIDTH_PERCENT = 0.8
    USER_TEXT_VERTICAL_POSITION_PERCENT = 0.10

    def __init__(self, static_folder):
        self.FONT_PATH_LACQUER = os.path.join(static_folder, "fonts", "Lacquer-Regular.ttf")
        self.FONT_PATH_NEW_SPIRIT = os.path.join(static_folder, "fonts", "NewSpiritSemiBoldCondensed.otf")
        
        self.font_lacquer = self._load_font(self.FONT_PATH_LACQUER, "Lacquer", 130)
        self.font_new_spirit = self._load_font(self.FONT_PATH_NEW_SPIRIT, "New Spirit", 1)

        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        self.redis_client = redis.from_url(redis_url)

    def _load_font(self, font_path, font_name, default_size):
        try:
            return ImageFont.truetype(font_path, default_size)
        except IOError:
            logging.warning(f"Could not load {font_name} font from {font_path}")
            return ImageFont.load_default()

    def _get_font_size(self, max_text_width, text, font):
        if not isinstance(max_text_width, int) or max_text_width <= 0:
            raise ValueError("Invalid max text width")
        if not text or not isinstance(text, str):
            raise ValueError("Invalid text")
        if not font:
            raise ValueError("Invalid font")

        font_size = 1
        while True:
            test_font = font.font_variant(size=font_size)
            text_width = test_font.getlength(text)
            if text_width > max_text_width:
                break
            font_size += 1
        return font_size - 1

    def _get_user_text(self, playlist_name, image_width, image_height):
        if not playlist_name or not isinstance(playlist_name, str):
            raise ValueError("Invalid playlist name")
        playlist_name = playlist_name.strip()
        user_and_cassies_text = playlist_name.split("'s")[0] + "'s"
        max_text_width = int(image_width * self.USER_TEXT_WIDTH_PERCENT)
        font_size = self._get_font_size(max_text_width, user_and_cassies_text, self.font_new_spirit)
        font = self.font_new_spirit.font_variant(size=font_size)
        text_width = font.getlength(user_and_cassies_text)
        user_text_position_x = (image_width - text_width) // 2
        user_text_position_y = int(image_height * self.USER_TEXT_VERTICAL_POSITION_PERCENT)
        return user_and_cassies_text, font, (user_text_position_x, user_text_position_y)

    def _get_trauma_text(self, image_width, image_height):
        if not isinstance(image_width, int) or image_width <= 0:
            raise ValueError("Invalid image width")
        if not isinstance(image_height, int) or image_height <= 0:
            raise ValueError("Invalid image height")


        trauma_list_text = "TRAUMA LIST"
        font_size = int(image_width * 0.05)  # 5% of image width
        font = self.font_lacquer.font_variant(size=font_size)
        trauma_text_width = font.getlength(trauma_list_text)
        right_padding = int(image_width * 0.05)  # 5% of image width
        top_padding = int(image_height * 0.20)  # 20% of image height from top
        trauma_text_position_x = image_width - trauma_text_width - right_padding
        trauma_text_position_y = top_padding

        return trauma_list_text, font, (trauma_text_position_x, trauma_text_position_y)

    def create_image(self, playlist_name):
        if not playlist_name or not isinstance(playlist_name, str):
            raise ValueError("Invalid playlist name")
        playlist_name = playlist_name.strip()

        img_cache_key = f"playlist_cover_{playlist_name}"
        cached_img = self.redis_client.get(img_cache_key)

        if cached_img:
            return BytesIO(cached_img)

        image_path = os.path.join(current_app.static_folder, "images", "artwork.png")
        with Image.open(image_path) as img:
            img = img.resize((640, 640), resample=Image.BICUBIC)
            img = img.convert("RGB")
            
            draw = ImageDraw.Draw(img)
            image_width, image_height = img.size
            user_text, font_new_spirit, user_text_position = self._get_user_text(playlist_name, image_width, image_height)
            draw.text(user_text_position, user_text, font=font_new_spirit, fill=self.TEXT_COLOR_NEW_SPIRIT)

            trauma_text, font_lacquer, trauma_text_position = self._get_trauma_text(image_width, image_height)
            draw.text(trauma_text_position, trauma_text, font=font_lacquer, fill=self.TEXT_COLOR_LACQUER)

            img_byte_arr = BytesIO()
            img.save(img_byte_arr, format="JPEG", quality=90)
            img_byte_arr.seek(0)

            self.redis_client.set(img_cache_key, img_byte_arr.getvalue(), ex=3600)  # Cache for 1 hour

        return img_byte_arr
