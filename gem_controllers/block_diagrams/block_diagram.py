from control_block_diagram import ControllerDiagram
from control_block_diagram.components import Point, Connection
from .stage_blocks import ext_ex_dc_cc, ext_ex_dc_ops, ext_ex_dc_output, perm_ex_dc_cc, perm_ex_dc_ops,\
    perm_ex_dc_output, pi_current_controller, pi_speed_controller, pmsm_cc, pmsm_ops, pmsm_output, scim_cc, scim_ops,\
    scim_output, series_dc_cc, series_dc_ops, series_dc_output, shunt_dc_cc, shunt_dc_ops, shunt_dc_output,\
    torque_controller, pmsm_speed_controller
import gem_controllers as gc


def build_block_diagram(controller, env_id, save_block_diagram):
    motor_type = gc.utils.get_motor_type(env_id)
    control_task = gc.utils.get_control_task(env_id)
    if save_block_diagram is not None:
        doc = ControllerDiagram(save_block_diagram)
    else:
        doc = ControllerDiagram()
    stages = get_stages(controller.controller, motor_type)
    start = Point(0, 0)

    inputs = dict()
    outputs = dict()
    connections = dict()
    connect_to_lines = dict()

    for idx, stage in enumerate(stages):
        start, inputs_, outputs_, connect_to_lines_, connections_ = stage(start, control_task)
        inputs = {**inputs, **inputs_}
        outputs = {**outputs, **outputs_}
        connect_to_lines = {**connect_to_lines, **connect_to_lines_}
        connections = {**connections, **connections_}

    for key in inputs.keys():
        if key in outputs.keys():
            connections[key] = Connection.connect(outputs[key], inputs[key][0], **inputs[key][1])

    for key in connect_to_lines.keys():
        if key in connections.keys():
            Connection.connect_to_line(connections[key], connect_to_lines[key][0], **connect_to_lines[key][1])

    doc.build()
    return doc


def get_stages(controller, motor_type):
    motor_check = motor_type in ['PMSM', 'SCIM', 'ShuntDc', 'SeriesDc', 'PermExDc', 'ExtExDc']
    stages = []
    if isinstance(controller, gc.PISpeedController):
        if motor_type == 'PMSM':
            stages.append(build_functions['PMSM_Speed_Controller'])
        else:
            stages.append(build_functions['PI_Speed_Controller'])
        controller = controller.torque_controller

    if isinstance(controller, gc.torque_controller.TorqueController):
        if motor_check:
            stages.append(build_functions[motor_type + '_OPS'])
        else:
            stages.append(build_functions['Torque_Controller'])
        controller = controller.current_controller

    if isinstance(controller, gc.PICurrentController):
        emf_feedforward = controller.emf_feedforward is not None
        if motor_check:
            stages.append(build_functions[motor_type + '_CC'](emf_feedforward))
        else:
            stages.append(build_functions['PI_Current_Controller'](emf_feedforward))

        stages.append((build_functions[motor_type + '_Output'](controller.emf_feedforward is not None)))

    return stages


build_functions = {
    'PI_Speed_Controller': pi_speed_controller,
    'PMSM_Speed_Controller': pmsm_speed_controller,
    'Torque_Controller': torque_controller,
    'PI_Current_Controller': pi_current_controller,
    'PMSM_OPS': pmsm_ops,
    'SCIM_OPS': scim_ops,
    'SeriesDc_OPS': series_dc_ops,
    'ShuntDc_OPS': shunt_dc_ops,
    'PermExDc_OPS': perm_ex_dc_ops,
    'ExtExDc_OPS': ext_ex_dc_ops,
    'PMSM_CC': pmsm_cc,
    'SCIM_CC': scim_cc,
    'SeriesDc_CC': series_dc_cc,
    'ShuntDc_CC': shunt_dc_cc,
    'PermExDc_CC': perm_ex_dc_cc,
    'ExtExDc_CC': ext_ex_dc_cc,
    'PMSM_Output': pmsm_output,
    'SCIM_Output': scim_output,
    'SeriesDc_Output': series_dc_output,
    'ShuntDc_Output': shunt_dc_output,
    'PermExDc_Output': perm_ex_dc_output,
    'ExtExDc_Output': ext_ex_dc_output,
}
