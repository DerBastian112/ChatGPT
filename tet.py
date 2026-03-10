import sys, time, shutil, random, msvcrt

class GameBoyBuffer:
    def __init__(self, width=100, height=50):
        self.width, self.height = width, height
        self.data = bytearray(width * height * 3)
        # ANSI: Alternativer Buffer, Cursor aus
        sys.stdout.write("\033[?1049h\033[?25l") 
        sys.stdout.flush()

    def set_pixel(self, x, y, r, g, b):
        if 0 <= x < self.width and 0 <= y < self.height:
            idx = (y * self.width + x) * 3
            self.data[idx:idx+3] = bytes([r, g, b])

    def render(self):
        # \033[H setzt den Cursor zurück nach oben links ohne zu flackern
        lines = ["\033[H"] 
        for y in range(0, self.height - 1, 2):
            row = []
            for x in range(self.width):
                i1, i2 = (y*self.width+x)*3, ((y+1)*self.width+x)*3
                row.append(f"\033[38;2;{self.data[i1]};{self.data[i1+1]};{self.data[i1+2]};"
                           f"48;2;{self.data[i2]};{self.data[i2+1]};{self.data[i2+2]}m▀")
            # \033[K löscht den Rest der Zeile
            lines.append("".join(row) + "\033[0m\033[K")
        
        # Sende alles in einem Rutsch, OHNE finales Newline am Ende des Buffers
        sys.stdout.write("\n".join(lines))
        sys.stdout.flush()

    def cleanup(self):
        sys.stdout.write("\033[?1049l\033[?25h")
        sys.stdout.flush()

C = {
    '*': (255, 0, 0), 'G': (255, 215, 0), 'g': (160, 130, 0),
    'R': (180, 40, 40), 'r': (120, 20, 20), 'W': (230, 230, 230),
    'F': (10, 10, 30), 'B': (60, 40, 20)
}

TOWER = [
    "      *      ", "      W      ", "     WWW     ", "    WGGGW    ",
    "    WgggW    ", "    WWWWW    ", "    W F W    ", "   WWWWWWW   ",
    "   R r R r   ", "   RWWWWWR   ", "   RW F WR   ", "   RWWWWWR   ",
    "  RRRRRRRRR  ", "  R F   F R  ", "  R   B   R  ", "  R F   F R  ",
    " RRRRRRRRRRR ", " RRRRRRRRRRR "
]

SHAPES = [
    [[1, 1, 1, 1]], 
    [[1, 1], [1, 1]], 
    [[0, 1, 0], [1, 1, 1]], 
    [[0, 1, 1], [1, 1, 0]], 
    [[1, 1, 0], [0, 1, 1]]
]

class Tetris:
    def __init__(self):
        self.gw, self.gh = 10, 20
        self.grid = [[None for _ in range(self.gw)] for _ in range(self.gh)]
        self.spawn()

    def spawn(self):
        self.p = random.choice(SHAPES)
        self.px, self.py = 3, 0
        self.c = (0, 255, 150)
        if self.collides(0, 0): self.grid = [[None for _ in range(self.gw)] for _ in range(self.gh)]

    def collides(self, dx, dy, p=None):
        p = p or self.p
        for y, row in enumerate(p):
            for x, v in enumerate(row):
                if v:
                    nx, ny = self.px + x + dx, self.py + y + dy
                    if nx < 0 or nx >= self.gw or ny >= self.gh or (ny >= 0 and self.grid[ny][nx]):
                        return True
        return False

    def draw(self, buf):
        for y, row in enumerate(TOWER):
            for x, char in enumerate(row):
                if char in C:
                    buf.set_pixel(x + 10, y + 10, *C[char])
                    buf.set_pixel(x + 75, y + 10, *C[char])
        ox, oy = 43, 5
        for y in range(self.gh + 1):
            for x in range(self.gw + 2):
                if x == 0 or x == self.gw + 1 or y == self.gh: buf.set_pixel(ox+x, oy+y, 80, 80, 80)
        for y, r in enumerate(self.grid):
            for x, col in enumerate(r):
                if col: buf.set_pixel(ox+1+x, oy+y, *col)
        for y, row in enumerate(self.p):
            for x, v in enumerate(row):
                if v: buf.set_pixel(ox+1+self.px+x, oy+self.py+y, *self.c)

def main():
    # WICHTIG: Fensterhöhe im Terminal muss groß genug sein!
    gb = GameBoyBuffer(width=100, height=46) 
    game = Tetris()
    last_fall = time.time()
    
    try:
        while True:
            if msvcrt.kbhit():
                k = msvcrt.getch().lower()
                if k == b'a' and not game.collides(-1, 0): game.px -= 1
                if k == b'd' and not game.collides(1, 0): game.px += 1
                if k == b'w':
                    rot = [list(r) for r in zip(*game.p[::-1])]
                    if not game.collides(0, 0, rot): game.p = rot
                if k == b's' and not game.collides(0, 1): game.py += 1
                if k == b'q': break

            if time.time() - last_fall > 0.3:
                if not game.collides(0, 1):
                    game.py += 1
                else:
                    for y, r in enumerate(game.p):
                        for x, v in enumerate(r):
                            if v: game.grid[game.py+y][game.px+x] = game.c
                    game.spawn()
                last_fall = time.time()

            gb.data = bytearray(b'\x05\x05\x10' * (gb.width * gb.height))
            game.draw(gb)
            gb.render()
            time.sleep(0.01)
            
    except Exception: pass
    finally: gb.cleanup()

if __name__ == "__main__":
    main()
