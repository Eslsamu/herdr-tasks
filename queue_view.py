"""Read-only, mouse-aware queue rendering for a normal terminal split."""
import curses
import unicodedata


def clean(value):
    return "".join(c if c == "\n" or not unicodedata.category(c).startswith("C") else " " for c in str(value))


def cells(value):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in value)


def clip(value, width):
    value = clean(value).replace("\n", " ")
    if width <= 0:
        return ""
    if cells(value) <= width:
        return value
    result, used = "", 0
    for char in value:
        cost = cells(char)
        if used+cost > width-1:
            break
        result += char
        used += cost
    return result+"…"


def wrap(value, width):
    """Preserve paragraphs and split by terminal cells, including long paths."""
    width = max(4, width)
    result = []
    for paragraph in clean(value).split("\n"):
        start, length = 0, len(paragraph)
        while start < length:
            end, used = start, 0
            while end < length:
                cost = cells(paragraph[end])
                if used+cost > width:
                    break
                used += cost
                end += 1
            if end == length:
                break
            space = paragraph.rfind(" ", start, end+1)
            cut = space if space > start else end
            result.append(paragraph[start:cut])
            start = cut
            while start < length and paragraph[start].isspace():
                start += 1
        result.append(paragraph[start:])
    return result


def counts(snapshot):
    tasks = snapshot["tasks"]
    return {
        "now": sum(t["status"] == "doing" for t in tasks),
        "next": sum(t["status"] == "queued" and not t["waiting_on"] for t in tasks),
        "waiting": sum(t["status"] == "blocked" or t["status"] == "queued" and t["waiting_on"] > 0 for t in tasks),
        "finished": sum(t["status"] in ("done", "cancelled") for t in tasks),
    }


class QueueView:
    def __init__(self):
        self.expanded = set()
        self.history = False
        self.selected = None
        self.scroll = 0
        self._positions = {}
        self._selected = None
        self._reveal = False

    def toggle(self, item):
        self.selected = item
        self._reveal = True
        if item == "history":
            self.history = not self.history
        elif isinstance(item, int):
            self.expanded.symmetric_difference_update({item})

    def rows(self, snapshot, width, compact=False):
        """Rows carry their own click target, including after wrapping/scrolling."""
        tasks = snapshot["tasks"]
        groups = [
            ("Now", [t for t in tasks if t["status"] == "doing"]),
            ("Waiting", [t for t in tasks if t["status"] == "blocked" or t["status"] == "queued" and t["waiting_on"]]),
            ("Next", [t for t in tasks if t["status"] == "queued" and not t["waiting_on"]]),
        ]
        finished = sorted((t for t in tasks if t["status"] in ("done", "cancelled")), key=lambda t:(t["updated"],t["id"]), reverse=True)
        rows = []
        def add(value, kind="text", target=None):
            rows.append({"text":value, "kind":kind, "target":target})
        def task_rows(task):
            owner = task["owner_name"] or "Unassigned"
            prefix = snapshot["board"]["name"].lower().replace(" ", "-")+"-"
            if owner.startswith(prefix):
                owner = owner[len(prefix):]
            marker = "v" if task["id"] in self.expanded else ">"
            title = f"{marker} #{task['id']}  {owner} · {task['title']}"
            add(clip(title, width), task["status"], task["id"])
            if task["id"] in self.expanded:
                if cells(title) > width:
                    for line in wrap(task["title"], width-3):
                        add("   "+line)
                for line in wrap(task["detail"] or "No description yet.", width-3):
                    add("   "+line)
                if task["note"]:
                    for line in wrap("Update: "+task["note"], width-3):
                        add("   "+line, "note")
                if task["waiting_on"]:
                    add(f"   Waiting for {task['waiting_on']} prerequisite task(s).", "blocked")
                if task["status"] in ("done", "cancelled"):
                    add("   "+task["status"].capitalize(), "note")
                if not compact:
                    add("")
            elif task["status"] == "blocked" and task["note"]:
                add("  "+clip(task["note"], width-2), "note")
            elif task["waiting_on"]:
                add(f"  Waiting for {task['waiting_on']} prerequisite task(s).", "note")
        for name, items in groups:
            if not items:
                continue
            if rows and not compact:
                add("")
            add(f"{name} · {len(items)}", "heading")
            for task in items:
                task_rows(task)
        if not rows:
            add("No active or queued work.")
        if finished:
            if not compact:
                add("")
            add(f"{'v' if self.history else '>'} Finished · {len(finished)}", "heading", "history")
            if self.history:
                for task in finished:
                    task_rows(task)
        selectable = [r["target"] for r in rows if r["target"] is not None]
        if self.selected not in selectable:
            self.selected = selectable[0] if selectable else None
        return rows

    def reconcile(self, rows, visible):
        """Anchor refreshes without undoing deliberate scrolling through details."""
        positions = {r["target"]: i for i,r in enumerate(rows) if r["target"] is not None}
        row = positions.get(self.selected)
        old_row = self._positions.get(self.selected)
        if row is not None:
            if old_row is not None:
                self.scroll += row-old_row
            if self._reveal or self.selected != self._selected:
                if row < self.scroll:
                    self.scroll = row
                elif row >= self.scroll+visible:
                    self.scroll = row-visible+1
        self.scroll = max(0,min(self.scroll,len(rows)-visible))
        self._positions, self._selected, self._reveal = positions, self.selected, False

    def move(self, rows, step, visible):
        targets = [(i,r["target"]) for i,r in enumerate(rows) if r["target"] is not None]
        if not targets:
            return
        current = next((i for i,(_,target) in enumerate(targets) if target == self.selected), 0)
        row, self.selected = targets[max(0,min(len(targets)-1,current+step))]
        if row < self.scroll:
            self.scroll = row
        elif row >= self.scroll+visible:
            self.scroll = max(0,row-visible+1)


def ui(screen, store, board=None):
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    screen.timeout(500)
    screen.keypad(True)
    color = curses.has_colors()
    if color:
        curses.start_color()
        try:
            curses.use_default_colors()
            background = -1
        except curses.error:
            background = curses.COLOR_BLACK
        curses.init_pair(1,curses.COLOR_CYAN,background)
        curses.init_pair(2,curses.COLOR_YELLOW,background)
    try:
        curses.mouseinterval(0)
        curses.mousemask(curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED | curses.BUTTON4_PRESSED | getattr(curses,"BUTTON5_PRESSED",0))
    except curses.error:
        pass
    view = QueueView()
    def put(y,x,value,width,attribute=0):
        try:
            if width > 0:
                screen.addstr(y,x,clip(value,width),attribute)
        except curses.error:
            pass
    while True:
        h,w = screen.getmaxyx()
        screen.erase()
        snapshot = store.snapshot(board) if board is not None else None
        title = snapshot["board"]["name"]+" / Tasks" if snapshot else "Tasks / no space queue linked"
        put(0,1,title,w-13,curses.A_BOLD)
        put(0,max(1,w-10),"[Close]",8,curses.A_BOLD)
        rows = []
        if snapshot:
            n = counts(snapshot)
            put(1,1,f"{n['now']} now · {n['next']} next · {n['waiting']} waiting",w-3)
            rows = view.rows(snapshot,max(8,w-3),compact=h < 12)
        elif h > 3:
            put(2,1,"Ask an agent in this space to join its queue.",w-3)
        content_y = 2 if h < 12 else 3
        visible = max(1,h-content_y-1)
        view.reconcile(rows,visible)
        hit_rows = {}
        for y,row in enumerate(rows[view.scroll:view.scroll+visible],content_y):
            if y >= h-1:
                break
            attribute = curses.A_BOLD if row["kind"] == "heading" else 0
            if row["kind"] == "doing" and color:
                attribute |= curses.color_pair(1)
            elif row["kind"] == "blocked" and color:
                attribute |= curses.color_pair(2)
            if row["target"] is not None and row["target"] == view.selected:
                attribute |= curses.A_REVERSE
            put(y,1,row["text"],w-3,attribute)
            if row["target"] is not None:
                hit_rows[y] = row["target"]
        footer = "Click / Enter: details · arrows: select · wheel: scroll · q: close"
        if w < 65:
            footer = "Click/Enter details · arrows · q close"
        if len(rows) > visible:
            footer = f"{view.scroll+1}-{min(len(rows),view.scroll+visible)}/{len(rows)} · "+footer
        put(h-1,1,footer,w-3)
        screen.refresh()
        key = screen.getch()
        if key in (ord('q'),27):
            return
        if key in (10,13,ord(' ')):
            view.toggle(view.selected)
        elif key in (curses.KEY_DOWN,ord('j')):
            view.move(rows,1,visible)
        elif key in (curses.KEY_UP,ord('k')):
            view.move(rows,-1,visible)
        elif key == curses.KEY_NPAGE:
            view.scroll += visible
        elif key == curses.KEY_PPAGE:
            view.scroll = max(0,view.scroll-visible)
        elif key == curses.KEY_MOUSE:
            try:
                _,x,y,_,state = curses.getmouse()
            except curses.error:
                continue
            if state & curses.BUTTON4_PRESSED:
                view.scroll = max(0,view.scroll-3)
            elif state & getattr(curses,"BUTTON5_PRESSED",0):
                view.scroll += 3
            elif state & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED):
                if y == 0 and w-10 <= x < w-3:
                    return
                if y in hit_rows and 0 < x < w-1:
                    view.toggle(hit_rows[y])
