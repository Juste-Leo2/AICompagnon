from PIL import Image, ImageDraw
import math
import copy
import threading
import queue
import random
import time

# --- Imports spécifiques pour ILI9488 ---
# Ces imports seront dans un try-except dans main_console.py,
# mais ici, on suppose qu'ils sont disponibles si ce module est utilisé.
try:
    import board
    import digitalio
    import busio
    from .ILI_librairie.ili9488 import ( # Import relatif car ILI_librairie est dans src
        ILI9488, COLOR_BLACK, COLOR_WHITE,
        DEFAULT_SPI_BAUDRATE,
        ILI9488_DEFAULT_TFTWIDTH, ILI9488_DEFAULT_TFTHEIGHT
    )
except ImportError:
    print("Attention: Les modules spécifiques au matériel (board, digitalio, busio, ILI9488) n'ont pas pu être importés.")
    print("Ce code ne fonctionnera que dans un environnement simulé ou si ces modules sont disponibles.")
    # Définir des placeholders pour que le reste du code ne plante pas immédiatement
    # à l'import, mais il ne fonctionnera pas sur le matériel.
    COLOR_BLACK = 0x000000
    COLOR_WHITE = 0xFFFFFF
    DEFAULT_SPI_BAUDRATE = 24000000
    ILI9488_DEFAULT_TFTWIDTH = 320
    ILI9488_DEFAULT_TFTHEIGHT = 480
    class ILI9488: # Dummy class
        def __init__(self, *args, **kwargs): pass
        def begin(self, *args, **kwargs): pass
        def setRotation(self, *args, **kwargs): pass
        def fillScreen(self, *args, **kwargs): pass
        def backlight_on(self, *args, **kwargs): pass
        def display(self, *args, **kwargs): pass
        def backlight_off(self, *args, **kwargs): pass
        @property
        def width(self): return ILI9488_DEFAULT_TFTWIDTH
        @property
        def height(self): return ILI9488_DEFAULT_TFTHEIGHT


# --- Code de dessin (DrawingTool et dessiner_yeux) ---
class DrawingTool:
    def __init__(self, image):
        self.image = image
        self.draw = ImageDraw.Draw(image)

    def dessiner_sourcil(self, centre_x, centre_y, courbure_gauche, courbure_droite, largeur_sourcil, decalage_y_sourcil, rotation_deg, epaisseur_trait, couleur="white"): # Modifié noir -> blanc par défaut
        start_x_trait = centre_x - largeur_sourcil / 2; end_x_trait = centre_x + largeur_sourcil / 2
        nombre_segments = 100; points_courbe = []
        pivot_x, pivot_y = centre_x, centre_y
        angle_rad = math.radians(-rotation_deg); cos_a, sin_a = math.cos(angle_rad), math.sin(angle_rad)
        if largeur_sourcil <= 0: return
        for i in range(nombre_segments + 1):
            fraction_x = i / nombre_segments
            x_pre_rot = start_x_trait + (end_x_trait - start_x_trait) * fraction_x
            courbure_factor = courbure_gauche * (1 - fraction_x) + courbure_droite * fraction_x
            y_relatif = - courbure_factor * math.sin(fraction_x * math.pi)
            y_pre_rot = pivot_y + y_relatif
            translated_x, translated_y = x_pre_rot - pivot_x, y_pre_rot - pivot_y
            rotated_x, rotated_y = translated_x * cos_a - translated_y * sin_a, translated_x * sin_a + translated_y * cos_a
            final_x, final_y = rotated_x + pivot_x, rotated_y + pivot_y + decalage_y_sourcil
            points_courbe.append((int(final_x), int(final_y)))
        if len(points_courbe) > 1: self.draw.line(points_courbe, fill=couleur, width=epaisseur_trait, joint='round')

    def dessiner_paupiere_sup_clignement(self, centre_x, centre_y, largeur_paupiere, decalage_y_paupiere, courbure_paupiere, epaisseur_trait, couleur="white"): # Modifié noir -> blanc par défaut
        start_x, end_x = centre_x - largeur_paupiere / 2, centre_x + largeur_paupiere / 2
        points = []
        for i in range(101):
            frac = i / 100; x = start_x + (end_x - start_x) * frac
            y = centre_y + decalage_y_paupiere + courbure_paupiere * math.sin(frac * math.pi)
            points.append((int(x), int(y)))
        if len(points) > 1: self.draw.line(points, fill=couleur, width=epaisseur_trait, joint='round')

    def dessiner_iris(self, centre_x, centre_y, taille_base_iris, ovale_parametre, iris_joie_intensite, blink_intensity, couleur_contour="white", couleur_remplissage=None, epaisseur_contour=1): # Modifié noir -> blanc par défaut
        rayon_x_base, rayon_y_base = max(1, taille_base_iris + ovale_parametre), max(1, taille_base_iris - ovale_parametre)
        rayons_iris_calcul = (1,1)
        scale_factor_blink = max(0, 1.0 - blink_intensity * 2.0)
        ellipse_alpha_factor = max(0, 1.0 - (iris_joie_intensite / 0.5)) * scale_factor_blink
        if ellipse_alpha_factor > 0:
            rayon_x_ellipse, rayon_y_ellipse = max(1, rayon_x_base * ellipse_alpha_factor), max(1, rayon_y_base * ellipse_alpha_factor)
            if rayon_x_ellipse >=1 and rayon_y_ellipse >=1 :
                ovale_coords = (centre_x - rayon_x_ellipse, centre_y - rayon_y_ellipse, centre_x + rayon_x_ellipse, centre_y + rayon_y_ellipse)
                current_epaisseur_ellipse = max(1, int(epaisseur_contour * ellipse_alpha_factor))
                self.draw.ellipse(ovale_coords, outline=couleur_contour, fill=couleur_remplissage, width=current_epaisseur_ellipse)
            rayons_iris_calcul = (rayon_x_ellipse, rayon_y_ellipse)
        joie_shape_alpha_factor = min(1, iris_joie_intensite / 0.7) * scale_factor_blink
        if joie_shape_alpha_factor > 0:
            largeur_joie = rayon_x_base
            hauteur_pointe_joie = max(5 * joie_shape_alpha_factor, (taille_base_iris * 0.6 + rayon_y_base * 0.4) * joie_shape_alpha_factor * 1.2)
            decalage_y_joie_base = -taille_base_iris * 0.2 * joie_shape_alpha_factor
            point_gauche, point_droite = (centre_x - largeur_joie, centre_y + decalage_y_joie_base), (centre_x + largeur_joie, centre_y + decalage_y_joie_base)
            point_haut_centre = (centre_x, centre_y - hauteur_pointe_joie + decalage_y_joie_base)
            current_epaisseur_joie = max(1, int(epaisseur_contour * joie_shape_alpha_factor))
            self.draw.line([point_gauche, point_haut_centre], fill=couleur_contour, width=current_epaisseur_joie, joint="round")
            self.draw.line([point_haut_centre, point_droite], fill=couleur_contour, width=current_epaisseur_joie, joint="round")
            if iris_joie_intensite > 0.6 or blink_intensity > 0.5: rayons_iris_calcul = (1, 1)
        if blink_intensity > 0.85: rayons_iris_calcul = (1,1)
        return (centre_x, centre_y), rayons_iris_calcul, (0,0,0,0)

    def dessiner_pupille(self, centre_iris, rayons_iris, decalage_x_pupille, decalage_y_pupille, taille_ratio=0.4, couleur="white"): # Modifié noir -> blanc par défaut
        if rayons_iris[0] <= 1 and rayons_iris[1] <= 1: return
        centre_pupille_x, centre_pupille_y = centre_iris[0] + decalage_x_pupille, centre_iris[1] + decalage_y_pupille
        rayon_pupille_x, rayon_pupille_y = max(1, rayons_iris[0] * taille_ratio), max(1, rayons_iris[1] * taille_ratio)
        rayon_pupille_x, rayon_pupille_y = min(rayon_pupille_x, rayons_iris[0]), min(rayon_pupille_y, rayons_iris[1])
        if rayon_pupille_x < 1 or rayon_pupille_y < 1 : return
        pupille_coords = (int(centre_pupille_x - rayon_pupille_x), int(centre_pupille_y - rayon_pupille_y), int(centre_pupille_x + rayon_pupille_x), int(centre_pupille_y + rayon_pupille_y))
        self.draw.ellipse(pupille_coords, fill=couleur, outline=couleur)

    def get_image(self): return self.image

def dessiner_yeux(image, parametres_yeux_list, centre_paire_x, espacement_yeux):
    outil_dessin = DrawingTool(image); demi_espacement = espacement_yeux / 2
    for eye_index, params_eye in enumerate(parametres_yeux_list):
        cx = int(centre_paire_x - demi_espacement) if eye_index == 0 else int(centre_paire_x + demi_espacement)
        cy = params_eye.get('centre_y', 160); blink_intensity = params_eye.get('blink_intensity', 0.0)
        iris_taille, iris_ovale = params_eye.get('iris_taille_base', 50), params_eye.get('iris_ovale_parametre', 0)
        iris_joie, iris_contour_clr = params_eye.get('iris_joie_intensite', 0.0), params_eye.get('iris_couleur_contour', "white") # Modifié
        iris_ep = params_eye.get('iris_epaisseur_contour', 3)
        pupille_dx, pupille_dy = params_eye.get('pupille_decalage_x', 0), params_eye.get('pupille_decalage_y', 0)
        pupille_ratio, pupille_clr = params_eye.get('pupille_taille_ratio', 0.5), params_eye.get('pupille_couleur', "white") # Modifié
        s_cg, s_cd, s_larg = params_eye.get('sourcil_courbure_gauche',15), params_eye.get('sourcil_courbure_droite',15), params_eye.get('sourcil_largeur',120)
        s_dy, s_rot, s_ep, s_clr = params_eye.get('sourcil_decalage_y',-70), params_eye.get('sourcil_rotation_deg',0), params_eye.get('sourcil_epaisseur',6), params_eye.get('sourcil_couleur',"white") # Modifié

        centre_iris, rayons_iris_pour_pupille, _ = outil_dessin.dessiner_iris(cx, cy, iris_taille, iris_ovale, iris_joie, blink_intensity, iris_contour_clr, epaisseur_contour=int(iris_ep))
        outil_dessin.dessiner_pupille(centre_iris, rayons_iris_pour_pupille, pupille_dx, pupille_dy, pupille_ratio, pupille_clr)
        outil_dessin.dessiner_sourcil(cx, cy, s_cg, s_cd, s_larg, s_dy, s_rot, int(s_ep), s_clr)
        if blink_intensity > 0:
            p_larg, p_ep, p_courb = iris_taille*2.2+abs(iris_ovale)*1.5, iris_ep+2, iris_taille*0.15
            decalage_y_haut_p, decalage_y_bas_p = -iris_taille*0.7, iris_taille*0.1
            curr_dy_p = decalage_y_haut_p + (decalage_y_bas_p - decalage_y_haut_p) * blink_intensity
            outil_dessin.dessiner_paupiere_sup_clignement(cx,cy,p_larg,curr_dy_p,p_courb,p_ep,iris_contour_clr) # iris_contour_clr est maintenant blanc
    return outil_dessin.get_image()
# --- Fin du code de dessin ---

# --- Définitions des Émotions ---
base_eye_params = {
    'centre_y': 160, 'iris_taille_base': 50, 'iris_ovale_parametre': 0,
    'iris_joie_intensite': 0.0, 'blink_intensity': 0.0,
    'iris_couleur_contour': "white", 'iris_epaisseur_contour': 3, # Modifié
    'pupille_decalage_x': 0, 'pupille_decalage_y': 0, 'pupille_taille_ratio': 0.4,
    'pupille_couleur': "white", 'sourcil_courbure_gauche': 15, # Modifié
    'sourcil_courbure_droite': 15, 'sourcil_largeur': 120,
    'sourcil_decalage_y': -70, 'sourcil_rotation_deg': 0,
    'sourcil_epaisseur': 6, 'sourcil_couleur': "white" # Modifié
}

EMOTIONS_ILI9488 = {
    "neutre": { "spacing": 200, "params_per_eye": [copy.deepcopy(base_eye_params), copy.deepcopy(base_eye_params)] },
    "joie": { "spacing": 190, "params_per_eye": [ {**base_eye_params, 'iris_joie_intensite': 1.0, 'iris_taille_base': 45, 'iris_ovale_parametre': 10, 'iris_epaisseur_contour': 4, 'sourcil_courbure_gauche': 25, 'sourcil_courbure_droite': 20, 'sourcil_rotation_deg': -8, 'sourcil_decalage_y': -78}, {**base_eye_params, 'iris_joie_intensite': 1.0, 'iris_taille_base': 45, 'iris_ovale_parametre': 10, 'iris_epaisseur_contour': 4, 'sourcil_courbure_gauche': 20, 'sourcil_courbure_droite': 25, 'sourcil_rotation_deg': 8, 'sourcil_decalage_y': -78} ] },
    "tristesse": { "spacing": 190, "params_per_eye": [ {**base_eye_params, 'iris_ovale_parametre': -10, 'pupille_taille_ratio':0.3, 'sourcil_courbure_gauche': -5, 'sourcil_courbure_droite': 10, 'sourcil_rotation_deg': 15, 'sourcil_decalage_y': -80}, {**base_eye_params, 'iris_ovale_parametre': -10, 'pupille_taille_ratio':0.3, 'sourcil_courbure_gauche': 10, 'sourcil_courbure_droite': -5, 'sourcil_rotation_deg': -15, 'sourcil_decalage_y': -80} ] },
    "colère": { "spacing": 160, "params_per_eye": [ {**base_eye_params, 'iris_taille_base': 45, 'iris_ovale_parametre': -5, 'pupille_taille_ratio':0.5, 'sourcil_courbure_gauche': 20, 'sourcil_courbure_droite': -15, 'sourcil_rotation_deg': -20, 'sourcil_decalage_y': -80}, {**base_eye_params, 'iris_taille_base': 45, 'iris_ovale_parametre': -5, 'pupille_taille_ratio':0.5, 'sourcil_courbure_gauche': -15, 'sourcil_courbure_droite': 20, 'sourcil_rotation_deg': 20, 'sourcil_decalage_y': -80} ] },
    "surprise": { "spacing": 200, "params_per_eye": [ {**base_eye_params, 'iris_taille_base': 60, 'iris_ovale_parametre': 5, 'pupille_taille_ratio':0.2, 'sourcil_courbure_gauche': 30, 'sourcil_courbure_droite': 30, 'sourcil_decalage_y': -80}, {**base_eye_params, 'iris_taille_base': 60, 'iris_ovale_parametre': 5, 'pupille_taille_ratio':0.2, 'sourcil_courbure_gauche': 30, 'sourcil_courbure_droite': 30, 'sourcil_decalage_y': -80} ] },
    "dégoût": { "spacing": 200, "params_per_eye": [ {**base_eye_params, 'iris_ovale_parametre': 5, 'pupille_taille_ratio':0.4, 'sourcil_courbure_gauche': 0, 'sourcil_courbure_droite': 15, 'sourcil_rotation_deg': -5, 'sourcil_decalage_y': -75}, {**base_eye_params, 'iris_ovale_parametre': 5, 'pupille_taille_ratio':0.4, 'sourcil_courbure_gauche': 15, 'sourcil_courbure_droite': 0, 'sourcil_rotation_deg': 5, 'sourcil_decalage_y': -75} ] },
    "peur": { "spacing": 180, "params_per_eye": [ {**base_eye_params, 'iris_taille_base': 65, 'pupille_taille_ratio':0.7, 'sourcil_courbure_gauche': 10, 'sourcil_courbure_droite': 10, 'sourcil_rotation_deg': 0, 'sourcil_decalage_y': -78}, {**base_eye_params, 'iris_taille_base': 65, 'pupille_taille_ratio':0.7, 'sourcil_courbure_gauche': 10, 'sourcil_courbure_droite': 10, 'sourcil_rotation_deg': 0, 'sourcil_decalage_y': -78} ] }
}


ANIM_EMOTIONS_AVAILABLE_ILI9488 = list(EMOTIONS_ILI9488.keys())


class EmotionAnimatorEngineILI9488:
    def __init__(self, command_queue, spi_bus, cs_pin, dc_pin, rst_pin, bl_pin, emotion_definitions=EMOTIONS_ILI9488):
        self.command_queue = command_queue
        self.emotion_definitions = emotion_definitions

        # --- Initialisation du driver ILI9488 ---
        self.ili_driver = ILI9488(spi_bus, cs_pin, dc_pin, rst_pin, bl_pin,
                                  width=ILI9488_DEFAULT_TFTWIDTH, # Natif 320
                                  height=ILI9488_DEFAULT_TFTHEIGHT) # Natif 480

        self.ili_driver.begin(spi_baudrate=DEFAULT_SPI_BAUDRATE)
        self.ili_driver.setRotation(1) # Paysage, résultats en 480x320
        self.ili_driver.fillScreen(COLOR_BLACK) # Écran noir au démarrage - MODIFIÉ
        self.ili_driver.backlight_on()
        print(f"Animation Eyes (ILI9488): Driver initialisé. Dimensions: {self.ili_driver.width}x{self.ili_driver.height}")

        self.img_width = self.ili_driver.width
        self.img_height = self.ili_driver.height
        self.centre_paire_x = self.img_width / 2

        initial_emotion_state = self.emotion_definitions.get("neutre", list(self.emotion_definitions.values())[0])
        for eye_params in initial_emotion_state['params_per_eye']:
            eye_params.setdefault('blink_intensity', 0.0)

        self.current_params_per_eye = copy.deepcopy(initial_emotion_state['params_per_eye'])
        self.current_spacing = initial_emotion_state['spacing']

        self.state_a_params_full, self.state_b_params_full = None, None
        self.is_emotion_animating, self.is_blinking = False, False
        self.animation_step, self.animation_total_steps = 0, 20

        self.blink_animation_phase, self.blink_animation_step = None, 0
        self.blink_closing_steps, self.blink_opening_steps, self.blink_hold_steps = 2, 3, 1

        self.current_pil_image = Image.new('RGB', (self.img_width, self.img_height), color='black') # MODIFIÉ

        self.numeric_param_keys = ['iris_taille_base', 'iris_ovale_parametre', 'iris_epaisseur_contour', 'iris_joie_intensite', 'pupille_decalage_x', 'pupille_decalage_y', 'pupille_taille_ratio', 'sourcil_courbure_gauche', 'sourcil_courbure_droite', 'sourcil_largeur', 'sourcil_decalage_y', 'sourcil_rotation_deg', 'sourcil_epaisseur']
        self.float_param_keys = ['pupille_taille_ratio', 'iris_joie_intensite']

        self.enable_auto_blink = True
        self.min_time_between_blinks = 2.0
        self.max_time_between_blinks = 7.0
        self._next_auto_blink_scheduled_time = 0
        self._schedule_next_auto_blink()

        self._running = True
        self._animation_thread = None
        print("Animation Eyes Engine (ILI9488): Moteur initialisé.")

    def _animation_loop(self):
        print("Animation Eyes Engine (ILI9488): Boucle d'animation interne démarrée.")
        target_fps = 20
        delay_between_frames = 1.0 / target_fps

        while self._running:
            loop_start_time = time.monotonic()

            self._check_command_queue_internal()

            needs_redraw = False
            if self.is_emotion_animating:
                self._animate_emotion_step_internal()
                needs_redraw = True

            if self.is_blinking:
                self._animate_blink_step_internal()
                needs_redraw = True

            if self.enable_auto_blink and time.time() >= self._next_auto_blink_scheduled_time:
                self._trigger_auto_blink_internal()

            if needs_redraw:
                self._redraw_eyes_internal()
                try:
                    self.ili_driver.display(self.current_pil_image)
                except Exception as e:
                    print(f"Animation Eyes Engine (ILI9488): Erreur affichage ILI: {e}")

            elapsed_time = time.monotonic() - loop_start_time
            sleep_duration = max(0, delay_between_frames - elapsed_time)
            time.sleep(sleep_duration)

        print("Animation Eyes Engine (ILI9488): Boucle d'animation interne terminée.")
        try:
            self.ili_driver.fillScreen(COLOR_BLACK)
            self.ili_driver.backlight_off()
        except Exception as e:
            print(f"Animation Eyes Engine (ILI9488): Erreur nettoyage écran: {e}")

    def _check_command_queue_internal(self):
        try:
            command_data = self.command_queue.get_nowait()
            if command_data:
                command_type = command_data.get("type")
                emotion_name = command_data.get("emotion")
                action = command_data.get("action")
                if command_type == "set_emotion" and emotion_name:
                    self.transition_to_emotion(emotion_name)
                elif command_type == "action" and action == "cligner":
                    self.start_blink_animation(commanded=True)
        except queue.Empty:
            pass
        except Exception as e:
            print(f"Animation Eyes Engine (ILI9488): Erreur dans _check_command_queue_internal: {e}")

    def _schedule_next_auto_blink(self):
        if not self.enable_auto_blink: return
        delay = random.uniform(self.min_time_between_blinks, self.max_time_between_blinks)
        self._next_auto_blink_scheduled_time = time.time() + delay

    def _trigger_auto_blink_internal(self):
        if self.enable_auto_blink and not self.is_blinking and not self.is_emotion_animating:
            self.start_blink_animation(commanded=False)
        self._schedule_next_auto_blink()

    def _redraw_eyes_internal(self):
        params_to_use = None; spacing_to_use = 0
        if self.is_emotion_animating and hasattr(self, '_temp_anim_params_per_eye') and hasattr(self, '_temp_anim_spacing'):
            params_to_use = self._temp_anim_params_per_eye
            spacing_to_use = self._temp_anim_spacing
        else:
            params_to_use = self.current_params_per_eye
            spacing_to_use = self.current_spacing

        final_params_for_drawing = copy.deepcopy(params_to_use)
        current_blink_val = getattr(self, '_current_blink_intensity_value', 0.0) if self.is_blinking else 0.0

        for eye_params in final_params_for_drawing: eye_params['blink_intensity'] = current_blink_val

        img = Image.new('RGB', (self.img_width, self.img_height), color='black') # MODIFIÉ
        self.current_pil_image = dessiner_yeux(img, final_params_for_drawing, self.centre_paire_x, spacing_to_use)

    def _animate_emotion_step_internal(self):
        if not self.is_emotion_animating or not self.state_a_params_full or not self.state_b_params_full:
            self.is_emotion_animating = False; return

        total_steps = self.animation_total_steps
        if self.animation_step <= total_steps:
            progress = self.animation_step / total_steps if total_steps > 0 else 1.0
            self._temp_anim_spacing = self.state_a_params_full['spacing'] + \
                               (self.state_b_params_full['spacing'] - self.state_a_params_full['spacing']) * progress
            interp_params_list = []
            for i in range(len(self.state_a_params_full['params_per_eye'])):
                eye_a = self.state_a_params_full['params_per_eye'][i]
                eye_b = self.state_b_params_full['params_per_eye'][i]
                interp_eye = {}
                val_a_cy, val_b_cy = eye_a.get('centre_y', 160), eye_b.get('centre_y', 160)
                interp_eye['centre_y'] = round(val_a_cy + (val_b_cy - val_a_cy) * progress)
                blink_a = eye_a.get('blink_intensity', 0.0); blink_b = eye_b.get('blink_intensity', 0.0)
                interp_eye['blink_intensity'] = blink_a + (blink_b - blink_a) * progress
                for key in self.numeric_param_keys:
                    default_val = base_eye_params.get(key, 0)
                    val_a = eye_a.get(key, default_val); val_b = eye_b.get(key, default_val)
                    interp_val = val_a + (val_b - val_a) * progress
                    if key not in self.float_param_keys: interp_val = round(interp_val)
                    interp_eye[key] = interp_val
                for k_non_num in eye_b: # Copie les paramètres non numériques (comme les couleurs)
                    if k_non_num not in self.numeric_param_keys and k_non_num not in ['centre_y', 'blink_intensity']:
                        interp_eye[k_non_num] = eye_b[k_non_num]
                interp_params_list.append(interp_eye)
            self._temp_anim_params_per_eye = interp_params_list
            self.animation_step += 1
        else:
            self.current_params_per_eye = copy.deepcopy(self.state_b_params_full['params_per_eye'])
            self.current_spacing = self.state_b_params_full['spacing']
            self.is_emotion_animating = False
            self.state_a_params_full, self.state_b_params_full = None, None
            self._temp_anim_params_per_eye = None; self._temp_anim_spacing = None

    def _animate_blink_step_internal(self):
        if not self.is_blinking: self._current_blink_intensity_value = 0.0; return

        blink_intensity_value = 0.0
        if self.blink_animation_phase == 'closing':
            self.blink_animation_step += 1
            progress = self.blink_animation_step / self.blink_closing_steps
            blink_intensity_value = min(1.0, progress)
            if self.blink_animation_step >= self.blink_closing_steps:
                blink_intensity_value = 1.0; self.blink_animation_phase = 'holding'; self.blink_animation_step = 0
        elif self.blink_animation_phase == 'holding':
            self.blink_animation_step += 1; blink_intensity_value = 1.0
            if self.blink_animation_step >= self.blink_hold_steps:
                self.blink_animation_phase = 'opening'; self.blink_animation_step = 0
        elif self.blink_animation_phase == 'opening':
            self.blink_animation_step += 1
            progress = self.blink_animation_step / self.blink_opening_steps
            blink_intensity_value = max(0.0, 1.0 - progress)
            if self.blink_animation_step >= self.blink_opening_steps:
                blink_intensity_value = 0.0; self.is_blinking = False
                self.blink_animation_phase = None; self.blink_animation_step = 0
        self._current_blink_intensity_value = blink_intensity_value

    def transition_to_emotion(self, emotion_name):
        if self.is_blinking: return
        target_emotion_state = self.emotion_definitions.get(emotion_name)
        if not target_emotion_state:
            print(f"Animation Eyes Engine (ILI9488): Emotion '{emotion_name}' non trouvée.")
            return

        final_target_state = copy.deepcopy(target_emotion_state)
        for eye_params_target in final_target_state['params_per_eye']: eye_params_target['blink_intensity'] = 0.0

        self.state_a_params_full = {'params_per_eye': copy.deepcopy(self.current_params_per_eye), 'spacing': self.current_spacing}
        self.state_b_params_full = final_target_state
        self.is_emotion_animating = True; self.animation_step = 0

    def start_blink_animation(self, commanded=False):
        if self.is_emotion_animating and not commanded: return
        if self.is_blinking and not commanded: return
        if self.is_emotion_animating and commanded:
            if hasattr(self, '_temp_anim_params_per_eye') and self._temp_anim_params_per_eye:
                self.current_params_per_eye = copy.deepcopy(self._temp_anim_params_per_eye)
                self.current_spacing = self._temp_anim_spacing
            self.is_emotion_animating = False
            self.state_a_params_full, self.state_b_params_full = None, None
            self._temp_anim_params_per_eye, self._temp_anim_spacing = None, None

        self.is_blinking = True; self.blink_animation_phase = 'closing'
        self.blink_animation_step = 0; self._current_blink_intensity_value = 0.0

    def stop(self):
        print("Animation Eyes Engine (ILI9488): Demande d'arrêt du moteur.")
        self._running = False
        self.enable_auto_blink = False
        if self._animation_thread and self._animation_thread.is_alive():
            self._animation_thread.join(timeout=1.0)
        print("Animation Eyes Engine (ILI9488): Moteur arrêté.")

_active_engine_instance_ili9488 = None
_animation_command_queue_ili9488 = None

def start_animation_display_ili9488(spi_bus, cs_pin, dc_pin, rst_pin, bl_pin):
    global _active_engine_instance_ili9488, _animation_command_queue_ili9488
    if _active_engine_instance_ili9488 is not None:
        print("Animation Eyes (ILI9488): Moteur déjà démarré.")
        return _animation_command_queue_ili9488

    print("Animation Eyes (ILI9488): Démarrage du moteur d'animation des yeux...")
    _animation_command_queue_ili9488 = queue.Queue()
    try:
        _active_engine_instance_ili9488 = EmotionAnimatorEngineILI9488(
            _animation_command_queue_ili9488,
            spi_bus, cs_pin, dc_pin, rst_pin, bl_pin
        )
    except Exception as e:
        print(f"Animation Eyes (ILI9488): ERREUR CRITIQUE à l'initialisation de EmotionAnimatorEngineILI9488: {e}")
        _active_engine_instance_ili9488 = None
        _animation_command_queue_ili9488 = None
        return None

    _active_engine_instance_ili9488._animation_thread = threading.Thread(
        target=_active_engine_instance_ili9488._animation_loop, daemon=True
    )
    _active_engine_instance_ili9488._animation_thread.start()
    return _animation_command_queue_ili9488

def stop_animation_display_ili9488():
    global _active_engine_instance_ili9488
    if _active_engine_instance_ili9488:
        print("Animation Eyes (ILI9488): Demande d'arrêt du moteur d'animation...")
        _active_engine_instance_ili9488.stop()
        _active_engine_instance_ili9488 = None
    print("Animation Eyes (ILI9488): Moteur (devrait être) arrêté.")

def send_animation_command_ili9488(command_type, emotion_name=None, action=None):
    global _animation_command_queue_ili9488
    if _animation_command_queue_ili9488 is None:
        print("Animation Eyes (ILI9488): La queue de commandes n'est pas initialisée.")
        return False

    command_data = {"type": command_type}
    if emotion_name: command_data["emotion"] = emotion_name.lower()
    if action: command_data["action"] = action.lower()

    try:
        _animation_command_queue_ili9488.put(command_data)
        return True
    except Exception as e:
        print(f"Animation Eyes (ILI9488): Erreur envoi commande: {e}")
        return False

# --- Section pour test direct (si ce fichier est exécuté) ---
if __name__ == '__main__':
    print("Exécution en mode test direct (simulation ILI9488).")

    # Simuler les broches GPIO et le bus SPI
    # (ces objets ne feront rien d'utile car les vraies bibliothèques ne sont pas là)
    class DummyPin:
        def __init__(self, name): self.name = name
        def switch_to_output(self, value): pass
        def __repr__(self): return f"DummyPin({self.name})"
    class DummySPI:
        def __init__(self): pass
        def configure(self, baudrate, polarity, phase): pass
        def try_lock(self): return True
        def unlock(self): pass
        def write(self, buffer): pass
        def __repr__(self): return "DummySPI"

    spi_bus_mock = DummySPI()
    cs_pin_mock = DummyPin("CS")
    dc_pin_mock = DummyPin("DC")
    rst_pin_mock = DummyPin("RST")
    bl_pin_mock = DummyPin("BL")

    cmd_q = start_animation_display_ili9488(spi_bus_mock, cs_pin_mock, dc_pin_mock, rst_pin_mock, bl_pin_mock)

    if cmd_q:
        print("Moteur d'animation démarré (simulé). Commandes disponibles via la console.")
        print("Exemples de commandes:")
        print("  emotion joie")
        print("  emotion tristesse")
        print("  cligner")
        print("  quitter")

        try:
            while True:
                user_input = input("Commande > ").strip().lower()
                if user_input == "quitter":
                    break
                elif user_input == "cligner":
                    send_animation_command_ili9488("action", action="cligner")
                elif user_input.startswith("emotion "):
                    emotion_name = user_input.split(" ", 1)[1]
                    if emotion_name in ANIM_EMOTIONS_AVAILABLE_ILI9488:
                        send_animation_command_ili9488("set_emotion", emotion_name=emotion_name)
                    else:
                        print(f"Emotion '{emotion_name}' non reconnue. Emotions disponibles: {ANIM_EMOTIONS_AVAILABLE_ILI9488}")
                elif user_input:
                    print("Commande non reconnue.")
        except KeyboardInterrupt:
            print("\nInterruption utilisateur.")
        finally:
            stop_animation_display_ili9488()
            print("Simulation terminée.")
    else:
        print("Échec du démarrage du moteur d'animation (simulé).")
