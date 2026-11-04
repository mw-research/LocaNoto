"""Files a user may attach to a mail: the own workspace and this chat's images.

    available(user, chat_id)          -> [name] that may be attached
    resolve(user, chat_id, names)     -> [(name, bytes, mime type)]; ValueError
    source(user, chat_id)             -> callable(names) for a mailbox connection

Only what the user alone controls leaves the house this way: documents of
the own (private) workspace -- uploads, taken-over web pages, created
files -- and images the user put into this chat. A document of a shared
workspace is not attachable: what others put there is not the sender's
to forward, and a mail is the one thing that cannot be taken back. To
send one anyway, move it into the own workspace first; that step is
deliberate and leaves a trace.

Chat images are named "chat-image-1", "chat-image-2", ... in the order
they appear in the chat.
"""
import mimetypes
import os

import paths

MAX_TOTAL_MB = paths.env_int("ATTACHMENT_MAX_MB", 20)
IMAGE_PREFIX = "chat-image-"


def _own_documents(user):
    import pipeline
    import raeume
    own = raeume.privat_kennung(user)
    return own, pipeline.dokumente(user, nur=[own]).get(own, [])


def _chat_images(user, chat_id):
    """[(label, stored path)] of the images in this chat."""
    if not chat_id:
        return []
    import chats
    if chat_id not in {k for k, _t, _g in chats.liste(user)}:
        return []
    out = []
    for m in chats.lade(user, chat_id):
        for path in m.get("bilder") or []:
            out.append((f"{IMAGE_PREFIX}{len(out) + 1}{os.path.splitext(path)[1].lower()}",
                        path))
    return out


def available(user, chat_id=None):
    _own, docs = _own_documents(user)
    return sorted(docs) + [label for label, _p in _chat_images(user, chat_id)]


def _image_label(name):
    """"chat-image-2" and "chat-image-2.jpg" both mean the second image."""
    base = os.path.splitext(name)[0] if name.lower().startswith(IMAGE_PREFIX) else name
    return base.lower()


def resolve(user, chat_id, names):
    """The files behind names, read now. ValueError names what is not allowed."""
    import aufnehmen
    import statefiles
    import vision
    names = [str(n).strip() for n in (names or []) if str(n).strip()]
    if not names:
        return []
    own, docs = _own_documents(user)
    images = {_image_label(label): (label, path) for label, path in _chat_images(user, chat_id)}
    out, total, refused = [], 0, []
    for name in names:
        if name in docs:
            path = aufnehmen.dokument_pfad(name, own)
            if not path or not statefiles.exists(path):
                refused.append(name)
                continue
            with statefiles.open(path, "rb") as f:
                data = f.read()
            out.append((name, data))
        elif _image_label(name) in images:
            label, path = images[_image_label(name)]
            data = vision.lade(path)
            if data is None:
                refused.append(name)
                continue
            out.append((label, data))
        else:
            refused.append(name)
            continue
        total += len(out[-1][1])
    if refused:
        raise ValueError(
            "Not attachable: " + ", ".join(refused) + ". Only documents of the own "
            "workspace and images of this chat can be attached"
            + (" (available: " + ", ".join(available(user, chat_id)[:20]) + ")"
               if available(user, chat_id) else "") + ".")
    if total > MAX_TOTAL_MB * 1024 * 1024:
        raise ValueError(f"Attachments larger than {MAX_TOTAL_MB} MB together.")
    return [(n, d, mimetypes.guess_type(n)[0] or "application/octet-stream")
            for n, d in out]


class Source:
    """What a mailbox connection calls to read attachments for this user.

    Called with names it returns the files; available() lists the names,
    so the tool description can tell the model what may be attached.
    """

    def __init__(self, user, chat_id):
        self.user, self.chat_id = user, chat_id

    def __call__(self, names):
        return resolve(self.user, self.chat_id, names)

    def available(self):
        return available(self.user, self.chat_id)


def source(user, chat_id):
    return Source(user, chat_id)
