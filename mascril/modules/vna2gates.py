from P13pt.mascril.measurement import MeasurementBase
from P13pt.drivers.bilt import Bilt, BiltVoltageSource, BiltVoltMeter
from P13pt.drivers.anritsuvna import AnritsuVNA


import time
import numpy as np
import os
import errno


class Measurement(MeasurementBase):
    params = {
        'Vdss': [10e-3],
        'Vg1s': [0.1],
        'Vg2s': [0.],
        'commongate': False,
        'Rg2': 100e3,
        'Rds': 2.2e3,
        'stabilise_time': 0.05,
        'comment': None,
        'data_dir': r'D:\MeasurementJANIS\Holger\test',
        'useVNA': False
    }

    observables = ['Vg1', 'Vg2', 'Vg2m', 'Ileak2', 'Vds', 'Vdsm', 'Rs']

    alarms = [
        ['np.abs(Ileak2) > 1e-8', MeasurementBase.ALARM_CALLCOPS],
        ['np.abs(Vg1-Vg2)', MeasurementBase.ALARM_SHOWVALUE]        # useful if we just want to know how much voltage
                                                                    # is applied between the two gates
    ]

    def measure(self, data_dir, comment, Vdss, Vg1s, Vg2s, commongate, Rg2, Rds, stabilise_time, useVNA, **kwargs):
        print "==================================="        
        print "Starting acquisition script..."

        # initialise instruments
        try:
            print "Setting up DC sources and voltmeters..."
            bilt = Bilt('TCPIP0::192.168.0.2::5025::SOCKET')
            self.sourceVds = sourceVds = BiltVoltageSource(bilt, "I1", initialise=False)
            self.sourceVg1 = sourceVg1 = BiltVoltageSource(bilt, "I2", initialise=False)
            self.sourceVg2 = sourceVg2 = BiltVoltageSource(bilt, "I3", initialise=False)
            self.meterVds = meterVds = BiltVoltMeter(bilt, "I5;C1", "2", "Vdsm")
            self.meterVg2 = meterVg2 = BiltVoltMeter(bilt, "I5;C3", "2", "Vg2m")
            print "DC sources and voltmeters are set up."
        except:
            print "There has been an error setting up DC sources and voltmeters."
            raise
        
        if useVNA:
            try:
                print "Setting up VNA"
                vna = AnritsuVNA('GPIB::6::INSTR')
                self.freqs = vna.get_freq_list()         # get frequency list
                print "VNA is set up."
            except:
                print "There has been an error setting up the VNA."
                raise

        timestamp = time.strftime('%Y-%m-%d_%Hh%Mm%Ss')

        # prepare saving data
        filename = timestamp + '_' + (comment if comment else '') + '.txt'
        self.prepare_saving(os.path.join(data_dir, filename))

        # prepare saving RF data
        if useVNA:
            spectra_fol = os.path.join(data_dir, timestamp)
            try:
                os.makedirs(spectra_fol)
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise

        # loops
        for Vds in Vdss:
            sourceVds.set_voltage(Vds)
            for Vg2 in Vg2s:
                if not commongate:
                    sourceVg2.set_voltage(Vg2)
                for Vg1 in Vg1s:
                    if self.flags['quit_requested']:
                        return locals()
    
                    sourceVg1.set_voltage(Vg1)
                    if commongate:
                        Vg2 = Vg1
                        sourceVg2.set_voltage(Vg1)
    
                    # stabilise
                    time.sleep(stabilise_time)
    
                    # measure
                    Vdsm = meterVds.get_voltage()
                    Vg2m = meterVg2.get_voltage()
    
                    # do calculations
                    Ileak2 = (Vg2-Vg2m)/Rg2
                    Rs = Rds*Vdsm/(Vds-Vdsm)
    
                    # save data
                    self.save_row(locals())

                    # save VNA data
                    if useVNA:
                        print "Getting VNA spectra..."
                        vna.single_sweep()
                        table = vna.get_table(range(1,5))
                        timestamp = time.strftime('%Y-%m-%d_%Hh%Mm%Ss')  
                        spectrum_file = timestamp+'_Vg1_%2.4f'%(Vg1)+'_Vg2_%2.4f'%(Vg2)+'_Vds_%2.4f'%(Vds)+'.txt'
                        np.savetxt(os.path.join(spectra_fol, spectrum_file), np.transpose(table))

        print "Acquisition done."
        
        return locals()

    def tidy_up(self):
        self.end_saving()

        print "Driving all voltages back to zero..."

        self.sourceVds.set_voltage(0.)
        self.sourceVg1.set_voltage(0.)
        self.sourceVg2.set_voltage(0.)


if __name__ == "__main__":
    m = Measurement()
    m.run()