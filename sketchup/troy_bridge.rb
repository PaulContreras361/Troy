# troy_bridge.rb - lets Troy draw in SketchUp Pro.
#
# Plain English:
#   SketchUp has no outside doorway like AutoCAD's COM, but it runs Ruby
#   plugins. This plugin checks a small "inbox" folder twice a second. Troy
#   drops a request there (a tiny JSON file like {"op":"box","width":12,...}),
#   this plugin draws it and writes the answer to the "outbox" folder.
#
#   Only the operations listed in OPS below exist. There is no "run any Ruby"
#   operation, so nothing Troy sends can do anything else to your computer.
#   Each request is ONE undo step in SketchUp (Edit > Undo / Ctrl+Z).
#
#   Folder: %LOCALAPPDATA%\TroyBridge\sketchup\inbox and \outbox
#   Install: install_laptop.py copies this file into SketchUp's Plugins folder.
#   Check:   Extensions menu > Troy Bridge > Status

require 'sketchup.rb'
require 'json'
require 'fileutils'

module TroyBridge
  VERSION = '1.0'
  ROOT = File.join(ENV['LOCALAPPDATA'] || File.expand_path('~'), 'TroyBridge', 'sketchup')
  INBOX = File.join(ROOT, 'inbox')
  OUTBOX = File.join(ROOT, 'outbox')
  UNITS = { 'ft' => :feet, 'feet' => :feet, 'in' => :inch, 'inch' => :inch, 'inches' => :inch,
            'm' => :m, 'meters' => :m, 'cm' => :cm, 'mm' => :mm, 'yd' => :yard }.freeze
  @handled = 0

  def self.len(value, unit)
    method = UNITS[(unit || 'ft').to_s.downcase] or raise ArgumentError, "unknown unit '#{unit}'"
    Float(value).send(method)
  end

  def self.pt(p, unit, z = 0)
    raise ArgumentError, 'a point must be [x, y] or [x, y, z]' unless p.is_a?(Array) && p.size >= 2
    Geom::Point3d.new(len(p[0], unit), len(p[1], unit), len(p[2] || z, unit))
  end

  def self.finish_group(group, req)
    group.name = req['name'].to_s if req['name']
    group.material = req['color'].to_s if req['color']
    { 'ok' => true, 'group' => group.name, 'id' => group.entityID }
  end

  # Flat face from corner points, pulled up by height (if given).
  def self.solid(ents, pts, height, req, unit)
    group = ents.add_group
    face = group.entities.add_face(pts)
    face.reverse! if face.normal.z < 0
    face.pushpull(len(height, unit)) if height && Float(height) != 0
    finish_group(group, req)
  end

  OPS = {
    'status' => lambda do |m, _r, _u|
      groups = m.entities.grep(Sketchup::Group).first(60).map { |g| { 'name' => g.name, 'id' => g.entityID } }
      { 'ok' => true, 'bridge' => VERSION, 'sketchup' => Sketchup.version, 'model' => m.title,
        'path' => m.path, 'entities' => m.entities.size, 'groups' => groups,
        'selected' => m.selection.size,
        'units' => (m.options['UnitsOptions']['LengthUnit'] rescue nil) }
    end,
    'box' => lambda do |m, r, u|
      x, y, z = (r['origin'] || [0, 0, 0]).map { |v| Float(v) }
      w, d = Float(r['width']), Float(r['depth'])
      pts = [[x, y], [x + w, y], [x + w, y + d], [x, y + d]].map { |p| pt(p, u, z || 0) }
      solid(m.active_entities, pts, r['height'], r, u)
    end,
    'rectangle' => lambda do |m, r, u|
      x, y, z = (r['origin'] || [0, 0, 0]).map { |v| Float(v) }
      w, d = Float(r['width']), Float(r['depth'])
      pts = [[x, y], [x + w, y], [x + w, y + d], [x, y + d]].map { |p| pt(p, u, z || 0) }
      solid(m.active_entities, pts, nil, r, u)
    end,
    'shape' => lambda do |m, r, u|   # any flat outline, optionally pulled up
      pts = (r['points'] || []).map { |p| pt(p, u, r['z'] || 0) }
      raise ArgumentError, 'shape needs at least 3 points' if pts.size < 3
      solid(m.active_entities, pts, r['height'], r, u)
    end,
    'wall' => lambda do |m, r, u|
      a = r['start']; b = r['end']
      t = Float(r['thickness'] || 0.5)
      dx = Float(b[0]) - Float(a[0]); dy = Float(b[1]) - Float(a[1])
      l = Math.hypot(dx, dy); raise ArgumentError, 'wall start and end are the same point' if l.zero?
      ox = -dy / l * t; oy = dx / l * t
      corners = [[a[0], a[1]], [b[0], b[1]], [Float(b[0]) + ox, Float(b[1]) + oy], [Float(a[0]) + ox, Float(a[1]) + oy]]
      solid(m.active_entities, corners.map { |p| pt(p, u, r['z'] || 0) }, r['height'] || 8, r, u)
    end,
    'cylinder' => lambda do |m, r, u|
      group = m.active_entities.add_group
      c = pt(r['center'] || [0, 0], u, r['z'] || 0)
      edges = group.entities.add_circle(c, Z_AXIS, len(r['radius'], u), Integer(r['segments'] || 24))
      face = group.entities.add_face(edges)
      face.reverse! if face.normal.z < 0
      face.pushpull(len(r['height'], u)) if r['height'] && Float(r['height']) != 0
      finish_group(group, r)
    end,
    'lines' => lambda do |m, r, u|
      pts = (r['points'] || []).map { |p| pt(p, u) }
      raise ArgumentError, 'lines needs at least 2 points' if pts.size < 2
      group = m.active_entities.add_group
      group.entities.add_edges(pts)
      finish_group(group, r)
    end,
    'move' => lambda do |m, r, u|
      g = find_group(m, r)
      v = r['by'] || [0, 0, 0]
      g.transform!(Geom::Transformation.translation(Geom::Vector3d.new(len(v[0], u), len(v[1], u), len(v[2] || 0, u))))
      { 'ok' => true, 'moved' => g.name }
    end,
    'delete' => lambda do |m, r, _u|
      g = find_group(m, r); name = g.name; g.erase!
      { 'ok' => true, 'deleted' => name, 'undo' => 'Ctrl+Z in SketchUp brings it back' }
    end,
    'zoom_extents' => lambda do |m, _r, _u|
      m.active_view.zoom_extents
      { 'ok' => true }
    end,
    'save' => lambda do |m, r, _u|
      path = r['path'].to_s
      if path.empty?
        raise ArgumentError, 'This model has never been saved - give a path ending in .skp' if m.path.to_s.empty?
        m.save
      else
        raise ArgumentError, 'path must end in .skp' unless path.downcase.end_with?('.skp')
        raise ArgumentError, "#{path} already exists - pick a new name" if File.exist?(path)
        m.save(path)
      end
      { 'ok' => true, 'saved' => m.path }
    end
  }.freeze

  NO_UNDO_STEP = %w[status zoom_extents save].freeze

  def self.find_group(m, r)
    g = m.entities.grep(Sketchup::Group).find do |e|
      (r['group_id'] && e.entityID == Integer(r['group_id'])) || (r['name'] && e.name == r['name'].to_s)
    end
    g or raise ArgumentError, "no group named '#{r['name'] || r['group_id']}'"
  end

  def self.handle(req)
    op = req['op'].to_s
    if op == 'undo'
      Sketchup.undo
      return { 'ok' => true, 'undone' => 1 }
    end
    fn = OPS[op] or return { 'ok' => false, 'error' => "unknown op '#{op}'", 'ops' => OPS.keys + ['undo'] }
    m = Sketchup.active_model
    return fn.call(m, req, req['unit']) if NO_UNDO_STEP.include?(op)

    m.start_operation("Troy: #{op}", true)
    begin
      out = fn.call(m, req, req['unit'])
      m.commit_operation
      out
    rescue StandardError
      m.abort_operation
      raise
    end
  end

  def self.poll
    Dir.glob(File.join(INBOX, '*.json')).sort.each do |f|
      req = nil
      begin
        req = JSON.parse(File.read(f))
        File.delete(f)
        res = handle(req)
      rescue StandardError => e
        File.delete(f) if File.exist?(f)
        res = { 'ok' => false, 'error' => "#{e.class}: #{e.message}" }
      end
      id = (req.is_a?(Hash) && req['id'].to_s =~ /\A[\w-]{1,64}\z/) ? req['id'].to_s : File.basename(f, '.json')
      tmp = File.join(OUTBOX, "#{id}.tmp")
      File.write(tmp, JSON.generate(res))
      File.rename(tmp, File.join(OUTBOX, "#{id}.json"))
      @handled += 1
    end
  end

  def self.start
    FileUtils.mkdir_p(INBOX)
    FileUtils.mkdir_p(OUTBOX)
    File.write(File.join(ROOT, 'alive.txt'), Time.now.to_s)
    @timer = UI.start_timer(0.5, true) do
      begin
        poll
      rescue StandardError => e
        puts "Troy Bridge: #{e.message}"
      end
    end
  end

  unless file_loaded?(__FILE__)
    start
    menu = UI.menu('Extensions').add_submenu('Troy Bridge')
    menu.add_item('Status') do
      UI.messagebox("Troy Bridge #{VERSION} is running.\nRequests handled: #{@handled}\nFolder: #{ROOT}")
    end
    file_loaded(__FILE__)
  end
end
