from PySide6.QtCore import QSize

from showsync.document import Document


def test_application_identity(qapp, window_factory):
    window = window_factory()
    assert qapp.applicationName() == 'showsync'
    assert qapp.applicationDisplayName() == 'showsync'
    assert qapp.desktopFileName() == 'showsync'
    for icon in (qapp.windowIcon(), window.windowIcon()):
        assert not icon.isNull()
        assert {16, 32, 48, 128, 256} <= {s.width() for s in icon.availableSizes()}
        assert not icon.pixmap(QSize(16, 16)).isNull()


def test_document_title(window_factory):
    window = window_factory(Document(title='Three-song ramp test'))
    assert window.windowTitle() == 'Three-song ramp test — showsync'
    window.dirty = True
    window.update_title()
    assert window.windowTitle() == 'Three-song ramp test * — showsync'
    window.document = Document()
    window.dirty = False
    window.update_title()
    assert window.windowTitle() == f'{window.document.display_title} — showsync'
