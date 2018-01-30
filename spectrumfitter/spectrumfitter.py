#!/usr/bin/python
import sys
import os
import imp
import inspect
from glob import glob
from P13pt.rfspectrum import Network
from P13pt.params_from_filename import params_from_filename
import ConfigParser

from PyQt5.QtCore import pyqtSignal, Qt, QSignalMapper
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
                         QPushButton, QFileDialog, QMessageBox, QSlider, QSpinBox, QLabel,
                         QWidgetItem, QSplitter, QComboBox, QCheckBox)

try:
    from PyQt5.QtCore import QString
except ImportError:
    QString = str

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar

import matplotlib.pyplot as plt
import numpy as np
import copy

def load_fitresults(filename, readfilenameparams=True, extrainfo=False):
    # read results file
    with open(filename, 'r') as f:
        # read the header
        column_header = None
        previous_line = None
        end_of_header = False
        data = []
        for line in f:
            line = line.strip()
            if line:
                if line[0] == '#':  # line is a comment line
                    line = line[1:].strip()
                    if line.startswith('thru:'):
                        thru = line[5:].strip()
                    elif line.startswith('dummy:'):
                        dummy = line[6:].strip()
                    elif line.startswith('dut:'):
                        dut = line[4:].strip()
                    elif line.startswith('model:'):
                        model = line[6:].strip()
                else:
                    # check if we reached the end of the header (or if we already had reached it previously)
                    # and if there is a last header line
                    if not end_of_header:
                        end_of_header = True
                        if previous_line:  # '#' was removed already
                            column_header = previous_line.split('\t')
                    data.append(line.split('\t'))
                previous_line = line
        data = zip(*data)  # transpose array

        # remove file name parameter columns if requested
        if not readfilenameparams:
            if not column_header[0] == 'filename':
                return None
            if not len(data):
                return None
            num_params = len(params_from_filename(data[0][0]))
            data = [data[0]]+data[num_params+1:]
            column_header = [column_header[0]]+column_header[num_params+1:]

        # put everything together
        if column_header and len(column_header) == len(data):
            data = dict(zip(column_header, data))
        else:
            data = None

    if not extrainfo:
        return data
    else:
        return data, dut, thru, dummy, model



def clearLayout(layout):
    for i in reversed(range(layout.count())):
        item = layout.itemAt(i)

        if isinstance(item, QWidgetItem):
            item.widget().close()
        else:
            clearLayout(item.layout())

        layout.removeItem(item)

class Fitter(QWidget):
    model_changed = pyqtSignal()
    model = None
    model_file = None
    sliders = {}
    checkboxes = {}

    def __init__(self, parent=None):
        super(Fitter, self).__init__(parent)

        self.txt_model = QLineEdit('Path to model...', self)
        self.btn_browsemodel = QPushButton('Browse', self)
        self.btn_loadmodel = QPushButton('Load', self)
        self.cmb_fitmethod = QComboBox(self)
        self.btn_fit = QPushButton('Fit', self)
        self.btn_fitall = QPushButton('Fit all', self)

        self.sliders = QWidget(self)
        self.sl_layout = QVBoxLayout()
        self.sliders.setLayout(self.sl_layout)

        self.txt_picfolder = QLineEdit('Path to picture folder...', self)
        self.btn_browsepicfolder = QPushButton('Browse', self)
        self.btn_savepic = QPushButton('Save current picture', self)
        self.btn_saveallpics = QPushButton('Save all pictures', self)

        self.txt_resultsfile = QLineEdit('Path to results file...', self)
        self.btn_browseresults = QPushButton('Browse', self)
        self.btn_saveresults = QPushButton('Save', self)
        self.btn_loadresults = QPushButton('Load', self)

        # set the layout
        layout = QVBoxLayout()
        for widget in [self.txt_model, self.btn_browsemodel, self.btn_loadmodel,
                       self.cmb_fitmethod, self.btn_fit, self.btn_fitall, self.sliders,
                       self.txt_picfolder, self.btn_browsepicfolder, self.btn_savepic, self.btn_saveallpics,
                       self.txt_resultsfile, self.btn_browseresults, self.btn_saveresults, self.btn_loadresults]:
            layout.addWidget(widget)
        self.setLayout(layout)

        # make connections
        self.btn_browsemodel.clicked.connect(self.browse_model)
        self.btn_loadmodel.clicked.connect(self.load_model)
        self.btn_fit.clicked.connect(self.fit_model)
        self.btn_fitall.clicked.connect(self.fit_all)
        self.cmb_fitmethod.currentIndexChanged.connect(self.fitmethod_changed)
        self.btn_browseresults.clicked.connect(self.browse_results)
        self.btn_saveresults.clicked.connect(self.save_results)
        self.btn_loadresults.clicked.connect(self.load_results)
        self.btn_browsepicfolder.clicked.connect(self.browse_picfolder)
        self.btn_savepic.clicked.connect(self.savepic)
        self.btn_saveallpics.clicked.connect(self.saveallpics)

    def browse_model(self):
        model_file, filter = QFileDialog.getOpenFileName(self, 'Choose model', directory=os.path.dirname(__file__))
        self.txt_model.setText(model_file)
        config.set('main', 'model', model_file)

    def load_model(self):
        # unload previous model
        clearLayout(self.sl_layout)
        self.sliders = {}
        self.checkboxes = {}
        self.cmb_fitmethod.clear()

        # check if we are dealing with a valid module
        filename = str(self.txt_model.text())
        mod_name, file_ext = os.path.splitext(os.path.split(filename)[-1])
        try:
            mod = imp.load_source(mod_name, filename)
        except IOError as e:
            QMessageBox.critical(self, "Error", "Could not load module: "+str(e.args[1]))
            return
        if not hasattr(mod, 'Model'):
            QMessageBox.critical(self, "Error", "Could not get correct class from file.")
            return
        self.model = getattr(mod, 'Model')()
        self.model_file = filename
        for member in inspect.getmembers(self.model, predicate=inspect.ismethod):
            if member[0].startswith('fit_'):
                # check if for this function we want to show checkboxes or not
                if len(inspect.getargspec(member[1]).args) == 4:
                    enable_checkboxes = True
                else:
                    enable_checkboxes = False
                self.cmb_fitmethod.addItem(member[0][4:], enable_checkboxes)
        for p in self.model.params:
            label = QLabel(p+' ['+str(self.model.params[p][4])+']')
            sl = QSlider(Qt.Horizontal)
            self.sliders[p] = sl
            sl.id = p
            sl.setMinimum(self.model.params[p][0])
            sl.setMaximum(self.model.params[p][1])
            sb = QSpinBox()
            sb.setMinimum(self.model.params[p][0])
            sb.setMaximum(self.model.params[p][1])
            cb = QCheckBox()
            self.checkboxes[p] = cb
            map = QSignalMapper(self)
            sl.valueChanged[int].connect(sb.setValue)
            sb.valueChanged[int].connect(sl.setValue)
            sl.valueChanged[int].connect(map.map)
            sl.setValue(self.model.params[p][2])
            map.mapped[QWidget].connect(self.value_changed)
            map.setMapping(sl, sl)
            l = QHBoxLayout()
            l.addWidget(label)
            l.addWidget(sl)
            l.addWidget(sb)
            l.addWidget(cb)
            self.sl_layout.addLayout(l)
        self.enable_checkboxes(self.cmb_fitmethod.itemData(self.cmb_fitmethod.currentIndex()))
        self.model_changed.emit()

    def fit_model(self):
        if self.model:
            fit_method = getattr(self.model, 'fit_'+str(self.cmb_fitmethod.currentText()))
            if self.cmb_fitmethod.itemData(self.cmb_fitmethod.currentIndex()):
                fit_method(self.parent().get_f(), self.parent().get_y(), self.checkboxes)
            else:
                fit_method(self.parent().get_f(), self.parent().get_y())
            for p in self.model.values:
                self.sliders[p].setValue(self.model.values[p]/self.model.params[p][3])

    def fit_all(self):
        for i in range(len(self.parent().dut_files)):
            self.parent().current_index = i
            self.parent().load_spectrum()
            self.fit_model()
            QApplication.processEvents()

    def value_changed(self, slider):
        self.model.values[slider.id] = slider.value()*self.model.params[slider.id][3]
        self.model_changed.emit()

    def enable_checkboxes(self, b=True):
        for p in self.checkboxes:
            self.checkboxes[p].setEnabled(b)

    def fitmethod_changed(self):
        enable_checkboxes = self.cmb_fitmethod.itemData(self.cmb_fitmethod.currentIndex())
        self.enable_checkboxes(enable_checkboxes)

    def update_values(self, values):
        self.model.values.update(values)
        for p in self.model.values:
            self.sliders[p].setValue(self.model.values[p]/self.model.params[p][3])
        self.model_changed.emit()

    def reset_values(self):
        if self.model:
            self.model.reset_values()
        for p in self.model.values:
            self.sliders[p].setValue(self.model.values[p]/self.model.params[p][3])
        self.model_changed.emit()

    def browse_results(self):
        results_file, filter = QFileDialog.getSaveFileName(self, 'Results file')
        self.txt_resultsfile.setText(results_file)

    def save_results(self):
        with open(self.txt_resultsfile.text(), 'w') as f:
            # write the header
            f.write('# fitting results generated by P13pt spectrum fitter\n')
            f.write('# thru:\t'+self.parent().thru_file+'\n')
            f.write('# dummy:\t' +self.parent().dummy_file+'\n')
            f.write('# dut:\t'+os.path.dirname(self.parent().dut_files[0])+'\n')
            f.write('# model:\t'+self.model_file+'\n')

            # determine columns
            f.write('# filename\t')
            for p in self.parent().dut.params:
                f.write(p+'\t')
            f.write('\t'.join([p for p in self.model.params]))
            f.write('\n')

            # write data
            filelist = sorted([filename for filename in self.parent().model_params])
            for filename in filelist:
                f.write(filename+'\t')
                for p in self.parent().dut.params:                  # TODO: what if some filenames do not contain all parameters? should catch exceptions
                    f.write(str(params_from_filename(filename)[p])+'\t')
                f.write('\t'.join([str(self.parent().model_params[filename][p]) for p in self.model.params]))
                f.write('\n')

    def load_results(self):
        # read the data
        data = load_fitresults(self.txt_resultsfile.text(), False)

        # check at least the filename field is present in the data
        if not data or 'filename' not in data:
            QMessageBox.warning(self, 'Error', 'Could not load data')
            return

        # empty the model parameters dictionary
        self.parent().model_params = {}

        # get a list of parameter names
        params = [p for p in data]
        unusable = []
        # now check float conversion compatibility of the data columns, removing the ones that we cannot use
        for p in params:
            try:
                data[p] = [float(x) for x in data[p]]
            except ValueError:
                unusable.append(p)
        for p in unusable:
            params.remove(p)

        for i,f in enumerate(data['filename']):
             # careful, this will also add the parameters from the filename to the model params
             # TODO: repair this (i.e. let the load_fitresults function inform the user about the number of filename parameters that need to be taken into account)
             values = [float(data[p][i]) for p in params]
             self.parent().model_params[f] = dict(zip(params, values))
             #print dict(zip(params, values))

    def browse_picfolder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Choose folder')
        self.txt_picfolder.setText(folder)

    def savepic(self):
        if self.parent().dut:
            name, ext = os.path.splitext(os.path.basename(self.parent().dut_files[self.parent().current_index]))
            self.parent().figure.savefig(os.path.join(self.txt_picfolder.text(), name+'.png'))

    def saveallpics(self):
        for i in range(len(self.parent().dut_files)):
            self.parent().current_index = i
            self.parent().load_spectrum()
            self.savepic()
            QApplication.processEvents()


class MainWindow(QSplitter):
    f = []
    dut_files = []
    duts = {}
    dut = None
    thru_file = ''
    dummy_file = ''
    current_index = 0
    line_r = None
    line_i = None
    model_params = {}

    def __init__(self, parent=None):
        super(MainWindow, self).__init__(parent)

        browse_icon = QIcon('../icons/folder.png')

        # set up data loading area
        self.data_loading = QWidget()
        self.txt_dut = QLineEdit('Path to DUT...')
        self.btn_browsedut = QPushButton(browse_icon, '')
        self.txt_thru = QLineEdit('Path to thru...')
        self.btn_browsethru = QPushButton(browse_icon, '')
        self.txt_dummy = QLineEdit('Path to dummy...')
        self.btn_browsedummy = QPushButton(browse_icon, '')
        self.btn_load = QPushButton('Load')
        self.btn_prev = QPushButton(QIcon('../icons/previous.png'), '')
        self.btn_next = QPushButton(QIcon('../icons/next.png'), '')
        l = QVBoxLayout()
        for field in [[QLabel('DUT:'), self.txt_dut, self.btn_browsedut],
                      [QLabel('Thru:'), self.txt_thru, self.btn_browsethru],
                      [QLabel('Dummy:'), self.txt_dummy, self.btn_browsedummy]]:
            hl = QHBoxLayout()
            for w in field:
                hl.addWidget(w)
            l.addLayout(hl)
        hl = QHBoxLayout()
        for w in [self.btn_load, self.btn_prev, self.btn_next]:
            hl.addWidget(w)
        l.addLayout(hl)
        self.data_loading.setLayout(l)

        # set up plotting area
        self.plotting = QWidget()
        self.figure = plt.figure()
        self.ax = self.figure.add_subplot(111)
        self.ax.set_xlabel('f [GHz]')
        self.ax.set_ylabel('Y12 [mS]')
        self.canvas = FigureCanvas(self.figure)
        self.toolbar = NavigationToolbar(self.canvas, self.plotting)
        l = QVBoxLayout()
        for w in [self.toolbar, self.canvas]:
            l.addWidget(w)
        self.plotting.setLayout(l)

        # set up left widget of the splitter
        self.left_widget = QWidget(self)
        l = QVBoxLayout()
        l.addWidget(self.data_loading)
        l.addWidget(self.plotting)
        l.setStretchFactor(self.plotting, 1)
        self.left_widget.setLayout(l)

        # set up fitting area
        self.fitter = Fitter(self)

        # make connections
        self.map_browse = QSignalMapper(self)
        for x in ['dut', 'thru', 'dummy']:
            self.__dict__['btn_browse'+x].clicked.connect(self.map_browse.map)
            self.map_browse.setMapping(self.__dict__['btn_browse'+x], x)
        self.map_browse.mapped[str].connect(self.browse)
        self.btn_load.clicked.connect(self.load)
        self.btn_prev.clicked.connect(self.prev_spectrum)
        self.btn_next.clicked.connect(self.next_spectrum)
        self.fitter.model_changed.connect(self.plot_fit)

        # load config
        if config.has_section('main'):
            if config.has_option('main', 'dut'): self.txt_dut.setText(config.get('main', 'dut'))
            if config.has_option('main', 'thru'): self.txt_thru.setText(config.get('main', 'thru'))
            if config.has_option('main', 'dummy'): self.txt_dummy.setText(config.get('main', 'dummy'))
            if config.has_option('main', 'model'): self.fitter.txt_model.setText(config.get('main', 'model'))
        else:
            config.add_section('main')

        # set up the splitter stretch factors
        self.setStretchFactor(0,1)
        self.setStretchFactor(1,3)

        # show the splitter
        self.show()

        # make the window big
        self.resize(1000,800)

        # Set window title
        self.setWindowTitle("Spectrum Fitter")

    def get_f(self):
        if self.dut:
            return self.dut.f
        else:
            return []

    def get_y(self):
        return self.dut.y[:,0,1]

    def browse(self, x):
        # open browser and update the text field
        folder = QFileDialog.getExistingDirectory(self, 'Choose dataset')
        self.__dict__['txt_'+str(x)].setText(folder)

        # save in config file
        config.set('main', str(x), folder)

    def load(self):
        self.clear_ax()
        self.current_index = 0
        self.model_params = {}
        self.duts = {}
        self.dut_files = sorted(glob(os.path.join(str(self.txt_dut.text()), '*.txt')),
                                key=lambda x: params_from_filename(x)['timestamp'])

        if len(self.dut_files) < 1:
            QMessageBox.warning(self, 'Warning', 'Please select a valid DUT folder')
            return

        dummy_files = glob(os.path.join(str(self.txt_dummy.text()), '*.txt'))
        if len(dummy_files) != 1:
            self.txt_dummy.setText('Please select a valid dummy folder')
            self.dummy_file = ''
        else:
            self.dummy_file, = dummy_files

        thru_files = glob(os.path.join(str(self.txt_thru.text()), '*.txt'))
        if len(thru_files) != 1:
            self.txt_thru.setText('Please select a valid thru folder')
            self.thru_file = ''
        else:
            self.thru_file, = thru_files

        self.load_spectrum(True)

    def clear_ax(self):
        for artist in self.ax.lines + self.ax.collections:
            artist.remove()
        self.ax.set_prop_cycle(None)
        self.ax.set_title('')
        self.canvas.draw()

    def load_spectrum(self, first_load=False):
        # clean up the axis
        self.clear_ax()
        self.line_r = None
        self.line_i = None

        params = params_from_filename(self.dut_files[self.current_index])
        if not first_load and self.dut_files[self.current_index] in self.duts:
            self.dut = dut = self.duts[self.dut_files[self.current_index]]
        else:
            # load spectra
            self.dut = dut = Network(self.dut_files[self.current_index])

            # TODO: tidy up this mess, especially the self.dut / dut weirdness (and be careful!)
            if self.dummy_file:
                dummy = Network(self.dummy_file)
            if self.thru_file:
                thru = Network(self.thru_file)
                if self.dummy_file:
                    dummy = dummy.deembed_thru(thru)
                self.dut = dut = dut.deembed_thru(thru)
            if self.dummy_file:
                dut.y -= dummy.y

            self.duts[self.dut_files[self.current_index]] = copy.copy(dut)

        if first_load:
            self.ax.set_xlim([min(dut.f/1e9), max(dut.f/1e9)])
        self.ax.plot(dut.f/1e9, dut.y[:,0,1].real*1e3, label='Real')
        self.ax.plot(dut.f/1e9, dut.y[:,0,1].imag*1e3, label='Imag')
        if first_load:
            self.figure.canvas.toolbar.update()
        self.ax.set_title(', '.join([key+'='+str(params[key]) for key in params]))

        # draw model if available
        self.f = dut.f
        if self.fitter.model:
            if self.dut_files[self.current_index] in self.model_params:
                self.fitter.update_values(self.model_params[self.dut_files[self.current_index]])
            else:
                self.fitter.reset_values()

        # update canvas
        self.canvas.draw()

    def prev_spectrum(self):
        self.current_index -= 1
        if self.current_index < 0:
            self.current_index = len(self.dut_files)-1
        self.load_spectrum()

    def next_spectrum(self):
        self.current_index += 1
        if self.current_index >= len(self.dut_files):
            self.current_index = 0
        self.load_spectrum()

    def plot_fit(self):
        if not self.dut_files:
            return

        # update model lines on plot
        f = np.asarray(self.f)
        y = -self.fitter.model.admittance(2.*np.pi*f, **self.fitter.model.values)  # - (minus) as a convention because we are looking at Y12

        if self.line_r:
            self.line_r.set_ydata(y.real*1e3)
            self.line_i.set_ydata(y.imag*1e3)
        else:
            self.line_r, = self.ax.plot(f/1e9, y.real*1e3, '-.')
            self.line_i, = self.ax.plot(f/1e9, y.imag*1e3, '-.')
        self.canvas.draw()

        # store new model data
        self.model_params[self.dut_files[self.current_index]] = copy.copy(self.fitter.model.values)


if __name__ == '__main__':
    # CD into directory where this script is saved
    d = os.path.dirname(__file__)
    if d != '': os.chdir(d)

    # Read config file
    config = ConfigParser.RawConfigParser()
    config.read('spectrumfitter.cfg')

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon('audacity.png'))

    mainwindow = MainWindow()

    # Start the main loop.
    ret = app.exec_()

    # Writing our configuration file to 'mdb.cfg'
    with open('spectrumfitter.cfg', 'wb') as configfile:
        config.write(configfile)

    sys.exit(ret)
